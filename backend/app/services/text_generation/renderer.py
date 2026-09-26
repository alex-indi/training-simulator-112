"""Text rendering contract and fallback orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TextGenerationTask(StrEnum):
    INCIDENT_REPORT = "INCIDENT_REPORT"
    RESPONSE_MESSAGE = "RESPONSE_MESSAGE"
    ASSESSMENT_SUMMARY = "ASSESSMENT_SUMMARY"


PROMPT_VERSIONS = {
    TextGenerationTask.INCIDENT_REPORT: "incident_operator_entry_v2",
    TextGenerationTask.RESPONSE_MESSAGE: "response_crew_message_v2",
    TextGenerationTask.ASSESSMENT_SUMMARY: "assessment_summary_v1",
}


@dataclass(frozen=True)
class TextGenerationRequest:
    task: TextGenerationTask
    facts: dict[str, Any]
    context: dict[str, Any] | None = None
    language: str = "ru"


@dataclass(frozen=True)
class TextGenerationResult:
    text: str
    provider: str
    model: str | None = None
    prompt_version: str = ""
    fallback_used: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None

    def snapshot(self, input_hash: str, origin: str = "GENERATED") -> dict[str, Any]:
        return {
            "rendered_text": self.text,
            "render_origin": origin,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "rendered_at": datetime.now(UTC).isoformat(),
            "input_hash": input_hash,
            "fallback_used": self.fallback_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    provider: str
    model: str | None


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_structured_output: bool = False
    supports_system_prompt: bool = False
    supports_json_schema: bool = False


class TextGenerationProvider(Protocol):
    name: str
    model: str | None
    capabilities: ProviderCapabilities

    async def generate(
        self, request: TextGenerationRequest, prompt: str
    ) -> TextGenerationResult: ...

    async def healthcheck(self) -> ProviderHealth: ...


class TemplateTextGenerationProvider:
    name = "template"
    model = None
    capabilities = ProviderCapabilities()

    async def generate(self, request: TextGenerationRequest, prompt: str) -> TextGenerationResult:
        facts = request.facts
        if request.task == TextGenerationTask.INCIDENT_REPORT:
            variant = facts.get("variant_facts") or {}
            if variant and facts.get("fallback_style") == "SCHOOL_FIRE":
                parts = [
                    f"{variant['observation']} на {variant['floor']} этаже школы, "
                    f"{variant['room']}; {variant['casualties']}"
                ]
            else:
                parts = [facts.get("description"), facts.get("caller_text")]
        else:
            parts = [facts.get("description") or facts.get("title")]
        text = "\n".join(str(value).strip() for value in parts if value and str(value).strip())
        if not text:
            raise ValueError("Невозможно сформировать текст без фактов")
        return TextGenerationResult(text=text, provider=self.name)

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth("AVAILABLE", self.name, None)


def prompt_for(task: TextGenerationTask) -> str:
    if task == TextGenerationTask.ASSESSMENT_SUMMARY:
        return (
            "Составь короткое профессиональное резюме учебной тренировки диспетчера ДДС 101 "
            "только по предоставленным системой фактам и отклонениям. Не придумывай события, "
            "ошибки и времена; не меняй severity. Отдельно и кратко назови критические, "
            "основные и дополнительные замечания, а также своевременные действия. "
            "Если категория пуста, прямо укажи это. Комментарий преподавателя используй "
            "только как контекст формулировки, не как источник новых фактов. "
            "Не выставляй итоговую оценку и не решай, пройдено ли занятие."
        )
    return (
        "Напиши короткое сообщение бригады для оперативного чата, как рабочую запись. "
        "Сохрани все переданные факты и числа. Не добавляй людей, адресов, служб, "
        "состояний или действий. Без канцелярита и пояснений. Верни только сообщение."
        if task == TextGenerationTask.RESPONSE_MESSAGE
        else "Напиши короткую оперативную запись для карточки диспетчера ДДС. "
        "Сохрани все переданные факты и числа. Не добавляй обстоятельств, людей, "
        "адресов, служб или состояний. Без пресс-релиза и пояснений. Верни только запись."
    )


def input_hash(request: TextGenerationRequest, provider: str, model: str | None) -> str:
    content = {
        "task": request.task.value,
        "language": request.language,
        "facts": request.facts,
        "context": request.context,
        "prompt_version": PROMPT_VERSIONS[request.task],
        "provider": provider,
        "model": model,
    }
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class AITextRenderer:
    def __init__(
        self,
        provider: TextGenerationProvider,
        *,
        enabled: bool = True,
        fallback_enabled: bool = True,
        timeout_seconds: float = 15,
        fallback: TextGenerationProvider | None = None,
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.fallback_enabled = fallback_enabled
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback or TemplateTextGenerationProvider()

    async def render(self, request: TextGenerationRequest) -> dict[str, Any]:
        prompt = prompt_for(request.task)
        version = PROMPT_VERSIONS[request.task]
        fingerprint = input_hash(request, self.provider.name, self.provider.model)
        started = monotonic()
        result = None
        provider_error = False
        if self.enabled and self.provider.name != "template":
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        self.provider.generate(request, prompt), timeout=self.timeout_seconds
                    )
                    _validate_text(result.text)
                    break
                except (Exception, asyncio.CancelledError) as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    result = None
                    provider_error = True
                    logger.warning(
                        "AI render failed: provider=%s model=%s task=%s attempt=%s error=%s",
                        self.provider.name,
                        self.provider.model,
                        request.task.value,
                        attempt + 1,
                        type(exc).__name__,
                    )
        if result is None:
            if not self.fallback_enabled and self.enabled and self.provider.name != "template":
                raise RuntimeError("AI rendering failed and fallback is disabled")
            result = await self.fallback.generate(request, prompt)
            _validate_text(result.text)
            result = TextGenerationResult(
                text=result.text, provider=result.provider, fallback_used=True
            )
        logger.info(
            "AI render: provider=%s model=%s task=%s duration=%.3f fallback=%s "
            "input_tokens=%s output_tokens=%s",
            result.provider,
            result.model,
            request.task.value,
            monotonic() - started,
            result.fallback_used,
            result.input_tokens,
            result.output_tokens,
        )
        snapshot = TextGenerationResult(
            text=result.text,
            provider=result.provider,
            model=result.model,
            prompt_version=version,
            fallback_used=result.fallback_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ).snapshot(fingerprint)
        snapshot["provider_error"] = provider_error
        return snapshot


def _validate_text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError("Invalid provider text")
    value.encode("utf-8", errors="strict")


def get_renderer(settings: Settings | None = None) -> AITextRenderer:
    from app.services.text_generation.providers import create_provider

    config = settings or get_settings()
    return AITextRenderer(
        create_provider(config),
        enabled=config.ai_text_enabled,
        fallback_enabled=config.ai_text_fallback_enabled,
        timeout_seconds=config.ai_text_timeout_seconds,
    )


async def renderer_for_database(database, settings: Settings | None = None) -> AITextRenderer:
    """A saved admin setting takes precedence over environment defaults."""
    from app.modules.admin.models import AIProviderConfig
    from app.modules.admin.secrets import decrypt_api_key

    config = settings or get_settings()
    stored = await database.get(AIProviderConfig, 1)
    if stored is not None:
        config = config.model_copy(
            update={
                "ai_text_enabled": stored.enabled,
                "ai_text_provider": stored.provider.lower(),
                "ai_text_model": stored.model,
                "ai_text_base_url": stored.base_url,
                "ai_text_timeout_seconds": stored.timeout_seconds,
                "ai_text_api_key": (
                    decrypt_api_key(stored.api_key_encrypted)
                    if stored.api_key_encrypted
                    else config.ai_text_api_key
                ),
            }
        )
    return get_renderer(config)
