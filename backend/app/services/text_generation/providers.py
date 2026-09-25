"""OpenAI and OpenAI-compatible HTTP adapters; protocol details stay here."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.text_generation.renderer import (
    ProviderCapabilities,
    ProviderHealth,
    TemplateTextGenerationProvider,
    TextGenerationRequest,
    TextGenerationResult,
)


class OpenAICompatibleProvider:
    name = "openai_compatible"
    completion_tokens_field = "max_tokens"
    capabilities = ProviderCapabilities(supports_system_prompt=True)

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        max_tokens: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def generate(self, request: TextGenerationRequest, prompt: str) -> TextGenerationResult:
        import json

        if not self.base_url or not self.model or (self.name == "openai" and not self.api_key):
            raise ValueError("AI provider is not configured")
        async with httpx.AsyncClient(timeout=None, transport=self.transport) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "task": request.task.value,
                                    "language": request.language,
                                    "facts": request.facts,
                                    "context": request.context,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    self.completion_tokens_field: self.max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str):
            raise ValueError("Invalid completion response")
        usage = data.get("usage") or {}
        return TextGenerationResult(
            text=content,
            provider=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def healthcheck(self) -> ProviderHealth:
        if not self.base_url or not self.model or (self.name == "openai" and not self.api_key):
            return ProviderHealth("MISCONFIGURED", self.name, self.model)
        try:
            async with httpx.AsyncClient(timeout=5, transport=self.transport) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                response.raise_for_status()
            return ProviderHealth("AVAILABLE", self.name, self.model)
        except (httpx.HTTPError, ValueError):
            return ProviderHealth("UNAVAILABLE", self.name, self.model)

    async def list_models(self) -> list[str]:
        if not self.base_url or (self.name == "openai" and not self.api_key):
            raise ValueError("AI provider is not configured")
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
            response.raise_for_status()
        data = response.json().get("data")
        if not isinstance(data, list):
            raise ValueError("Invalid models response")
        models = {
            item["id"].strip()
            for item in data
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
        }
        return sorted(models, key=str.casefold)


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    completion_tokens_field = "max_completion_tokens"

    def __init__(self, *, model: str, api_key: str, max_tokens: int = 300):
        super().__init__(
            base_url="https://api.openai.com/v1",
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
        )


def create_provider(settings: Settings):
    if not settings.ai_text_enabled or settings.ai_text_provider == "template":
        return TemplateTextGenerationProvider()
    if settings.ai_text_provider == "openai":
        return OpenAIProvider(
            model=settings.ai_text_model,
            api_key=settings.ai_text_api_key or settings.openai_api_key,
            max_tokens=settings.ai_text_max_output_tokens,
        )
    if settings.ai_text_provider == "openai_compatible":
        key = settings.ai_text_api_key
        if settings.ai_text_base_url.rstrip("/") == "https://api.openai.com/v1":
            key = key or settings.openai_api_key
        return OpenAICompatibleProvider(
            base_url=settings.ai_text_base_url,
            model=settings.ai_text_model,
            api_key=key,
            max_tokens=settings.ai_text_max_output_tokens,
        )
    raise ValueError(f"Unknown AI text provider: {settings.ai_text_provider}")
