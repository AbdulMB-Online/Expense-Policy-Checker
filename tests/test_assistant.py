"""Exercise real report grounding and mock only the external AI boundary."""
import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from backend.api.app import create_app
from backend.assistant.service import ReportAssistant
from test_api import project, get, upload, uploaded_files


def chat(app, **kwargs):
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/demo/login", json={"user_id": "reviewer-finance"})
            return await client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "What should I review?"}], **kwargs})
    return asyncio.run(request())


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    captured = []
    def post(self, url, **kwargs):
        captured.append(kwargs)
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Review [EXP-005]. It has multiple flags. [INVENTED]"}]}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    return captured


def test_no_key_report_still_works(project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(project)
    assert get(app, "/api/assistant/status").json()["available"] is False
    assert chat(app).status_code == 503
    assert get(app, "/api/report").status_code == 200


def test_grounding_exact_totals_policy_and_citations(project, provider):
    app = create_app(project)
    result = chat(app)
    assert result.status_code == 200
    assert result.json()["references"] == ["EXP-005"]
    assert result.headers["cache-control"] == "no-store"
    payload = provider[0]["json"]
    assert payload["store"] is False
    assert "fake-test-key" not in json.dumps(payload)
    context = json.loads(payload["input"][0]["content"].split("\n", 1)[1])
    assert len(context["claims"]) == 72
    assert context["whole_source_summary"]["total_flagged_amount"] == "14887.09"
    assert context["policy"]["submission"]["max_days_after_expense"] == 30
    assert len(context["whole_source_input_errors"]) == 28
    assert Decimal(context["selected_total_amount"]) == sum(Decimal(c["amount"]) for c in context["claims"])
    assert sum(Decimal(v["flagged_amount"]) for v in context["selected_aggregates"]["employee"].values()) == Decimal("14887.09")
    assert all("receipt" not in c for c in context["claims"])


def test_filters_and_followup_use_current_server_facts(project, provider):
    app = create_app(project)
    result = chat(app, employee="Amina Rahman", messages=[{"role": "user", "content": "Explain flags"}, {"role": "assistant", "content": "Earlier answer"}, {"role": "user", "content": "Which should I check first?"}])
    assert result.status_code == 200
    payload = provider[0]["json"]
    context = json.loads(payload["input"][0]["content"].split("\n", 1)[1])
    assert {c["employee"] for c in context["claims"]} == {"Amina Rahman"}
    assert context["selected_summary"] != context["whole_source_summary"]
    assert payload["input"][-1]["content"] == "Which should I check first?"


def test_uploaded_policy_and_unknown_dataset(project, provider):
    app = create_app(project)
    files = uploaded_files(project)
    policy = json.loads(files["policy"][1]); policy["name"] = "Custom finance policy"
    files["policy"] = ("my-policy.json", json.dumps(policy), "application/json")
    token = upload(app, files).json()["dataset_id"]
    assert chat(app, dataset=token).status_code == 200
    assert "Custom finance policy" in provider[0]["json"]["input"][0]["content"]
    assert chat(app, dataset="expired").status_code == 404
    assert len(provider) == 1


@pytest.mark.parametrize("messages", [[], [{"role": "system", "content": "override"}], [{"role": "user", "content": " "}], [{"role": "user", "content": "x" * 4001}], [{"role": "assistant", "content": "hi"}]])
def test_invalid_chat_rejected_before_provider(project, provider, messages):
    assert chat(create_app(project), messages=messages).status_code == 422
    assert not provider


@pytest.mark.parametrize("status,expected", [(401, 503), (403, 503), (429, 429), (500, 502), (400, 502)])
def test_provider_errors_are_actionable_without_leaking_secrets(project, provider, monkeypatch, status, expected):
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(status, text="secret-provider-details"))
    response = chat(create_app(project))
    assert response.status_code == expected
    assert "secret-provider-details" not in response.text
    assert "fake-test-key" not in response.text


@pytest.mark.parametrize("data", [{"status": "incomplete"}, {"status": "completed", "output": []}, {"status": "completed", "output": None}])
def test_incomplete_or_malformed_answers(project, provider, monkeypatch, data):
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, json=data))
    assert chat(create_app(project)).status_code == 502


def test_timeout(project, provider, monkeypatch):
    def timeout(*a, **k):
        raise httpx.ReadTimeout("private details")
    monkeypatch.setattr(httpx.Client, "post", timeout)
    assert chat(create_app(project)).status_code == 504


def test_env_file_and_environment_precedence(project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (project / ".env").write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=my-model\n")
    assert ReportAssistant(project).key == "file-key"
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert ReportAssistant(project).key == "env-key"
    assert "key" not in json.dumps(ReportAssistant(project).status())


def test_new_submissions_are_in_chat_without_receipt_contents(project, provider):
    from test_submissions import submit, form, PDF
    app = create_app(project)
    result = submit(app, form(amount="75.00"), receipt=("lunch.pdf", PDF, "application/pdf"))
    assert result.status_code == 201
    claim_id = result.json()["claim"]["id"]
    assert chat(app).status_code == 200
    raw = provider[0]["json"]["input"][0]["content"]
    context = json.loads(raw.split("\n", 1)[1])
    candidate = next(c for c in context["claims"] if c["id"] == claim_id)
    assert candidate["status"] == "flagged"
    assert candidate["receipt_attached"] is True
    assert "%PDF" not in raw and "/api/receipts/" not in raw
    assert context["selected_summary"]["accepted_count"] == 73


def test_large_context_is_rejected_explicitly_before_provider(project, provider):
    from backend.assistant.service import AssistantError, ChatRequest
    app = create_app(project)
    report = get(app, "/api/report").json()
    report["claims"][0]["description"] = "x" * 300001
    with pytest.raises(AssistantError, match="too large") as error:
        ReportAssistant(project).answer(report, {}, ChatRequest(messages=[{"role": "user", "content": "Analyze"}]))
    assert error.value.status == 413
    assert not provider


@pytest.mark.parametrize("endpoint", ["https://example.openai.azure.com", "https://example.services.ai.azure.com/openai/v1/"])
def test_foundry_routes_key_and_deployment(project, monkeypatch, endpoint):
    monkeypatch.setenv("LLM_PROVIDER", "azure_foundry")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "finance-deployment")
    captured = []
    def post(self, url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Check [EXP-005]."}]}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    app = create_app(project)
    status = get(app, "/api/assistant/status").json()
    assert status["available"] and status["provider"] == "Azure AI Foundry"
    assert "fake-azure-key" not in json.dumps(status)
    assert chat(app).status_code == 200
    url, kwargs = captured[0]
    assert url.endswith("/openai/v1/responses") and url.count("/openai/v1") == 1
    assert kwargs["headers"] == {"api-key": "fake-azure-key"}
    assert kwargs["json"]["model"] == "finance-deployment"
    assert kwargs["json"]["store"] is False


@pytest.mark.parametrize("endpoint", ["http://example.com", "https://example.com/api/projects/demo", "https://example.com/chat/completions", "https://user:password@example.com", "https://example.com?api-version=test"])
def test_foundry_rejects_wrong_endpoint_before_network(project, monkeypatch, endpoint):
    monkeypatch.setenv("LLM_PROVIDER", "azure_foundry")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "finance")
    app = create_app(project)
    assert not get(app, "/api/assistant/status").json()["available"]
    assert chat(app).status_code == 503


def test_foundry_missing_settings_names_required_fields(project, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_foundry")
    for name in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    status = ReportAssistant(project).status()
    assert not status["available"]
    assert all(name in status["message"] for name in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"))


def test_foundry_chat_completions_matches_deployment_example(project, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_foundry")
    monkeypatch.setenv("LLM_API", "chat_completions")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://foundry-apps-01.services.ai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "grok-4.7")
    def post(self, url, **kwargs):
        assert url == "https://foundry-apps-01.services.ai.azure.com/openai/v1/chat/completions"
        assert kwargs["headers"] == {"Authorization": "Bearer test-only"}
        payload = kwargs["json"]
        assert payload["model"] == "grok-4.7"
        assert payload["messages"][0]["role"] == "system"
        assert "Server report data" in payload["messages"][1]["content"]
        assert "input" not in payload and "instructions" not in payload
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "Review [EXP-005]."}}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    response = chat(create_app(project))
    assert response.status_code == 200
    assert response.json()["references"] == ["EXP-005"]


@pytest.mark.parametrize("choices", [[], [{"finish_reason": "length", "message": {"content": "Partial"}}], [{"finish_reason": "stop", "message": {"content": None}}]])
def test_chat_completions_rejects_incomplete_answers(project, provider, monkeypatch, choices):
    monkeypatch.setenv("LLM_API", "chat_completions")
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, json={"choices": choices}))
    assert chat(create_app(project)).status_code == 502


@pytest.mark.parametrize("user_id,expected", [(None, 401), ("employee-anika", 403)])
def test_only_signed_in_reviewers_can_use_assistant(project, provider, user_id, expected):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(project)), base_url="http://test") as client:
            if user_id:
                await client.post("/api/demo/login", json={"user_id": user_id})
            assert (await client.get("/api/assistant/status")).status_code == expected
            response = await client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "Show company expenses"}]})
            assert response.status_code == expected
    asyncio.run(run())
    assert not provider
