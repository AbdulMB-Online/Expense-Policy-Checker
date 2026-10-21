"""Server-only configuration for OpenAI and Azure AI Foundry APIs."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


class AssistantConfig:
    def __init__(self, root: Path):
        settings = {**dotenv_values(root / ".env"), **os.environ}

        def value(name, default=""):
            return (settings.get(name) or default).strip()

        self.provider = value("LLM_PROVIDER", "openai").lower()
        self.api = value("LLM_API", "responses").lower()
        self.error = ""
        self.url = "https://api.openai.com/v1/responses"
        if self.provider == "azure_foundry":
            self.key = value("AZURE_OPENAI_API_KEY")
            self.model = value("AZURE_OPENAI_DEPLOYMENT")
            endpoint = value("AZURE_OPENAI_ENDPOINT").rstrip("/")
            self.headers = {"api-key": self.key}
            if not all((self.key, self.model, endpoint)):
                self.error = "Set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT in the server .env file, then restart the server."
            if endpoint:
                try:
                    parsed = urlsplit(endpoint)
                    valid = (
                        parsed.scheme == "https"
                        and parsed.hostname
                        and not parsed.username
                        and not parsed.password
                        and not parsed.query
                        and not parsed.fragment
                        and parsed.path in ("", "/openai/v1")
                        and parsed.port in (None, 443)
                    )
                except ValueError:
                    valid = False
                if not valid:
                    self.error = "Use the HTTPS Foundry resource endpoint, optionally ending in /openai/v1/. Do not use a project, deployment, or chat/completions URL."
                else:
                    self.url = endpoint + ("/responses" if parsed.path else "/openai/v1/responses")
        else:
            self.key = value("OPENAI_API_KEY")
            self.model = value("OPENAI_MODEL", "gpt-5.5")
            self.headers = {"Authorization": f"Bearer {self.key}"}
            if self.provider != "openai":
                self.error = "Set LLM_PROVIDER to azure_foundry or openai in the server .env file."
            elif not self.key:
                self.error = "Add OPENAI_API_KEY to the server .env file and restart the server to enable report chat."

        if self.api == "chat_completions":
            self.url = self.url.removesuffix("responses") + "chat/completions"
            # Match the OpenAI client authentication in the Foundry example.
            self.headers = {"Authorization": f"Bearer {self.key}"}
        elif self.api != "responses":
            self.error = "Set LLM_API to chat_completions or responses in .env."

    def status(self):
        return {
            "available": not bool(self.error),
            "model": self.model,
            "provider": "Azure AI Foundry" if self.provider == "azure_foundry" else "OpenAI",
            "message": self.error or "Ready to discuss your report.",
        }
