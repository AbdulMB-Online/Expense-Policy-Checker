"""Exercise authenticated receipt uploads, real decoders, and the mocked AI boundary."""

import asyncio
import base64
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from backend.api.app import create_app
from backend.services.validation import MAX_RECEIPT_BYTES
from test_submissions import project, report, request


SUGGESTIONS = {
    "is_receipt": True,
    "merchant": "Joe's Cafe",
    "title": "Lunch at Joe's Cafe",
    "description": "Sandwich and coffee, including tax and tip.",
    "date": "2026-10-21",
    "amount": "20.28",
    "currency": "USD",
    "category": "meals",
    "nights": None,
    "warnings": [],
}


def image_file(format="PNG", pages=1):
    output = BytesIO()
    with Image.new("RGB", (600, 800), "white") as image:
        if format == "PDF":
            image.save(output, format=format, save_all=True, append_images=[image] * (pages - 1))
        else:
            image.save(output, format=format)
    return output.getvalue()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_foundry")
    monkeypatch.setenv("LLM_API", "chat_completions")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://receipt-test.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-receipt-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "grok-4.7")
    captured = []
    options = {"status": 200, "suggestions": SUGGESTIONS.copy()}

    def post(self, url, **kwargs):
        captured.append(kwargs["json"])
        if options.get("exception"):
            raise options["exception"]
        if "body" in options:
            return httpx.Response(options["status"], json=options["body"])
        content = json.dumps(options["suggestions"])
        if url.endswith("responses"):
            body = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}]}
        else:
            body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        return httpx.Response(options["status"], json=body)

    monkeypatch.setattr(httpx.Client, "post", post)
    return captured, options


def extract(app, contents=None, name="receipt.png", **data):
    return request(app, "POST", "/api/receipts/extract", data=data, files={
        "receipt": (name, contents if contents is not None else image_file(), "application/octet-stream"),
    })


@pytest.mark.parametrize("api", ["chat_completions", "responses"])
def test_extracts_suggestions_without_saving_claims(project, provider, monkeypatch, api):
    captured, _ = provider
    monkeypatch.setenv("LLM_API", api)
    app = create_app(project)
    before = report(app)["overview"]
    response = extract(app)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["amount"] == "20.28" and result["date"] == "2026-10-21"
    assert result["title"] == "Lunch at Joe's Cafe" and result["model"] == "grok-4.7"
    assert "employee" not in result and "is_receipt" not in result
    assert report(app)["overview"] == before
    payload = captured[0]
    assert payload["store"] is False
    assert "fake-receipt-key" not in json.dumps(payload)
    if api == "chat_completions":
        assert payload["response_format"]["json_schema"]["strict"] is True
        content = payload["messages"][1]["content"]
        url = content[1]["image_url"]["url"]
    else:
        assert payload["text"]["format"]["strict"] is True
        content = payload["input"][0]["content"]
        url = content[1]["image_url"]
    assert "meals" in content[0]["text"]
    assert base64.b64decode(url.split(",", 1)[1]).startswith(b"\xff\xd8\xff")


def test_pdf_pages_are_rendered_as_images(project, provider):
    captured, _ = provider
    result = extract(create_app(project), image_file("PDF", pages=2), "receipt.pdf")
    assert result.status_code == 200
    images = captured[0]["messages"][1]["content"][1:]
    assert len(images) == 2
    assert all(item["image_url"]["url"].startswith("data:image/jpeg;base64,") for item in images)


@pytest.mark.parametrize("contents,status", [
    (b"not an image", 422),
    (b"\x89PNG\r\n\x1a\ncorrupt", 422),
    (b"%PDF-corrupt", 422),
    (b"x" * (MAX_RECEIPT_BYTES + 1), 413),
])
def test_invalid_uploads_never_reach_provider(project, provider, contents, status):
    captured, _ = provider
    assert extract(create_app(project), contents).status_code == status
    assert captured == []


def test_excessive_pdf_pages_rejected_before_provider(project, provider):
    captured, _ = provider
    assert extract(create_app(project), image_file("PDF", pages=6)).status_code == 422
    assert captured == []


def test_excessive_image_dimensions_rejected_before_provider(project, provider, monkeypatch):
    captured, _ = provider
    monkeypatch.setattr("backend.services.receipt_images.MAX_IMAGE_PIXELS", 100)
    assert extract(create_app(project)).status_code == 422
    assert captured == []


def test_jpeg_orientation_is_normalized_and_metadata_removed(project, provider):
    captured, _ = provider
    output = BytesIO()
    with Image.new("RGB", (40, 60), "white") as image:
        exif = image.getexif()
        exif[274] = 6
        exif[270] = "Private camera metadata"
        image.save(output, "JPEG", exif=exif)
    assert extract(create_app(project), output.getvalue()).status_code == 200
    url = captured[0]["messages"][1]["content"][1]["image_url"]["url"]
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as sent:
        assert sent.size == (60, 40)
        assert not sent.getexif()


def test_missing_receipt_details_stay_unknown(project, provider):
    _, options = provider
    options["suggestions"].update(date=None, amount=None, title=None, description=None, category="hotel")
    result = extract(create_app(project)).json()
    assert result["date"] is None and result["amount"] is None
    assert result["title"] is None and result["description"] is None
    assert any("nights" in note for note in result["warnings"])


@pytest.mark.parametrize("changes", [
    {"amount": "NaN"}, {"amount": -10}, {"amount": "-1.00"},
    {"date": "2026-02-30"}, {"date": "10/21/2026"},
    {"nights": 0}, {"employee": "Invented"}, {"title": "x" * 151},
])
def test_untrusted_provider_fields_are_validated(project, provider, changes):
    _, options = provider
    options["suggestions"].update(changes)
    assert extract(create_app(project)).status_code == 502


@pytest.mark.parametrize("currency", ["EUR", None])
def test_unknown_or_foreign_currency_does_not_fill_usd_amount(project, provider, currency):
    _, options = provider
    options["suggestions"].update(currency=currency, category="invented", date=None)
    result = extract(create_app(project)).json()
    assert result["amount"] is None and result["category"] is None and result["date"] is None
    assert any("no conversion" in warning for warning in result["warnings"])


def test_nonreceipt_rejected(project, provider):
    _, options = provider
    options["suggestions"]["is_receipt"] = False
    assert extract(create_app(project)).status_code == 422


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"refusal": "Cannot read", "content": None}}]},
])
def test_malformed_and_incomplete_answers_fail_safely(project, provider, body):
    _, options = provider
    options["body"] = body
    assert extract(create_app(project)).status_code == 502


@pytest.mark.parametrize("status,expected", [(401, 503), (403, 503), (429, 429), (500, 502)])
def test_provider_errors_are_actionable_and_do_not_leak_details(project, provider, status, expected):
    _, options = provider
    options.update(status=status, body={"error": "private-provider-details"})
    response = extract(create_app(project))
    assert response.status_code == expected
    assert "private-provider-details" not in response.text


def test_timeout_is_retryable(project, provider):
    _, options = provider
    options["exception"] = httpx.ReadTimeout("private-provider-details")
    response = extract(create_app(project))
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


def test_sign_in_required_and_employee_can_extract(project, provider):
    captured, _ = provider
    app = create_app(project)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            files = {"receipt": ("receipt.png", image_file(), "image/png")}
            assert (await client.post("/api/receipts/extract", files=files)).status_code == 401
            assert captured == []
            users = (await client.get("/api/demo/accounts")).json()
            employee = next(user for user in users if user["role"] == "employee")
            await client.post("/api/demo/login", json={"user_id": employee["id"]})
            assert (await client.post("/api/receipts/extract", files=files)).status_code == 200

    asyncio.run(run())


def test_missing_configuration_and_unknown_dataset(project, provider, monkeypatch):
    captured, _ = provider
    monkeypatch.delenv("AZURE_OPENAI_API_KEY")
    app = create_app(project)
    assert extract(app).status_code == 503
    assert extract(app, dataset="missing").status_code == 404
    assert captured == []
