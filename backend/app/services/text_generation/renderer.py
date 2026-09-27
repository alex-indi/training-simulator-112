"""Text rendering contract and fallback orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
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
    TextGenerationTask.INCIDENT_REPORT: "incident_operator_entry_v7",
    TextGenerationTask.RESPONSE_MESSAGE: "response_crew_message_v4",
    TextGenerationTask.ASSESSMENT_SUMMARY: "assessment_summary_v2",
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
            additional = facts.get("additional_conditions") or []
            if variant and facts.get("fallback_style") == "SCHOOL_FIRE":
                observation = str(variant.get("observation") or "").strip()
                floor = str(variant.get("floor") or "").strip()
                room = str(variant.get("room") or "").strip()
                casualties = str(variant.get("casualties") or "").strip()

                incident_parts = []

                if observation:
                    if floor:
                        incident_parts.append(f"{observation} на {floor} этаже")
                    else:
                        incident_parts.append(observation)

                if room:
                    incident_parts.append(room)

                if casualties:
                    incident_parts.append(casualties)

                incident_parts.extend(
                    str(item).strip()
                    for item in additional
                    if item and str(item).strip()
                )

                parts = [", ".join(incident_parts)]
            else:
                incident_parts = [
                    str(value).strip()
                    for value in (
                        facts.get("description"),
                        facts.get("caller_text"),
                    )
                    if value and str(value).strip()
                ]

                incident_parts.extend(
                    str(item).strip()
                    for item in additional
                    if item and str(item).strip()
                )

                parts = [", ".join(incident_parts)]
        elif request.task == TextGenerationTask.ASSESSMENT_SUMMARY:
            parts = [
                f"Обработано карточек: {facts['cards_processed']}; завершено: {facts['completed']}."
            ]
            for label, key in (
                ("Критические замечания", "critical_errors"),
                ("Основные замечания", "major_errors"),
                ("Дополнительные замечания", "additional_errors"),
            ):
                issues = facts.get(key) or []
                if issues:
                    shown = "; ".join(str(issue)[:350] for issue in issues[:3])
                    remainder = f"; ещё {len(issues) - 3}" if len(issues) > 3 else ""
                    parts.append(f"{label} ({len(issues)}): {shown}{remainder}.")
                else:
                    parts.append(f"{label}: нет.")
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
        return """
Ты формируешь итоговое автоматическое резюме учебной тренировки
диспетчера ДДС 101 для преподавателя.

Твоя задача — НЕ оценивать обучаемого самостоятельно, а кратко и понятно
объяснить результаты, которые уже рассчитала система.

ИСТОЧНИК ИСТИНЫ:
Используй только данные, переданные в facts и context.

В facts уже находятся:
- количество обработанных карточек;
- количество завершённых карточек;
- рассчитанные времена реакции;
- своевременные действия;
- найденные системой отклонения;
- заранее определённая системой тяжесть каждого отклонения:
  critical, major или additional;
- при наличии — краткая хронология работы.

Ты НЕ должен самостоятельно искать новые ошибки или переоценивать существующие.

КРИТИЧЕСКИ ВАЖНО:
- не придумывай события;
- не придумывай действия обучаемого;
- не придумывай времена реакции;
- не придумывай причины ошибок;
- не меняй severity отклонения;
- не переносить замечание из одной категории в другую;
- не называй действие ошибкой, если система не передала его как отклонение;
- не делай выводов о профессиональной пригодности, компетентности,
  психологическом состоянии или общей квалификации обучаемого;
- не оценивай правильность пожарной тактики;
- не оценивай качество работы бригады;
- не добавляй нормативы, которых нет во входных данных;
- не выставляй итоговую оценку;
- не пиши, что занятие «сдано», «не сдано», «пройдено» или «не пройдено».

Если система передала конкретное время реакции и норматив,
используй их в резюме.

Например:
«Статус “Прибытие” установлен через 60 с после сообщения бригады
при нормативе 45 с.»

Не округляй и не изменяй переданные системой значения.

СТРУКТУРА РЕЗЮМЕ:

1. Сначала дай очень короткий общий итог работы:
   сколько карточек обработано и завершено.

2. Затем кратко отметь действия, выполненные своевременно.
   Не перечисляй каждое действие, если их много — выдели наиболее значимые.

3. После этого опиши замечания строго по категориям:
   - Критические;
   - Основные;
   - Дополнительные.

4. Для каждого замечания по возможности указывай:
   - что произошло;
   - какое действие ожидалось;
   - фактическое время реакции;
   - установленный норматив,
   если эти данные присутствуют во входных фактах.

5. В конце дай короткое нейтральное заключение:
   на какие действия преподавателю стоит обратить внимание при разборе занятия.

СТИЛЬ:
- профессиональный;
- спокойный;
- конкретный;
- без канцелярита;
- без общих фраз вроде «в целом обучаемый показал хорошие результаты»,
  если это не следует непосредственно из фактов;
- без повторения одной и той же ошибки несколько раз;
- без длинного пересказа всей хронологии;
- ориентировочно 5–10 коротких предложений;
- если ошибок мало, резюме должно быть ещё короче.

Если в определённой категории замечаний нет, прямо напиши:
«Критических замечаний нет.»
или
«Дополнительных замечаний нет.»

Если вообще нет отклонений, так и напиши:
«Система не зафиксировала отклонений от контролируемых критериев.»

КОММЕНТАРИЙ ПРЕПОДАВАТЕЛЯ:
Если в context передан комментарий преподавателя, можешь учитывать его
только для акцентов и формулировки итогового текста.

Комментарий преподавателя НЕ позволяет:
- придумывать новые системные ошибки;
- менять severity;
- изменять рассчитанные времена;
- противоречить данным facts.

ФИНАЛЬНАЯ ОЦЕНКА:
Итоговую оценку выставляет только преподаватель.
Не предлагай оценку и не рекомендуй конкретный балл.

Верни только готовое резюме.
Без пояснений о своей работе, без JSON и без вступления вроде
«Вот итоговое резюме».
""".strip()

    if task == TextGenerationTask.RESPONSE_MESSAGE:
        return """
Ты формулируешь короткое учебное сообщение от выездной пожарной бригады 101
для диспетчера ДДС.

Это рабочая оперативная информация о ходе реагирования.
Это НЕ официальный отчёт, НЕ сообщение пресс-службы и НЕ литературное описание.

СТИЛЬ:
- одна короткая фраза, максимум две;
- пиши максимально лаконично;
- язык естественный, как короткий доклад бригады диспетчеру;
- допустимы неполные предложения;
- допустимо начало со строчной буквы;
- финальная точка не обязательна;
- никаких приветствий, вступлений и объяснений;
- не пиши «сообщаем», «по прибытии установлено», «на место происшествия прибыл расчёт»,
  если это можно сказать проще.

ХОРОШИЙ СТИЛЬ:
«выехали к месту»
«прибыли, дым со 2 этажа, идем на разведку»
«на месте, сильное задымление, начинаем разведку»
«очаг в кабинете, приступили к тушению»
«пожар ликвидирован»

ПЛОХОЙ СТИЛЬ:
«Пожарно-спасательное подразделение прибыло на место происшествия.
В настоящее время проводится разведка помещений.»

КРИТИЧЕСКИ ВАЖНО:
- используй только факты, переданные в facts;
- не придумывай этаж, помещение, очаг пожара, пострадавших, распространение огня;
- не придумывай действия, которые ещё не произошли;
- не меняй числа;
- не меняй состояние происшествия;
- если каких-то сведений нет, не заполняй их самостоятельно.

Верни только готовый текст сообщения, без кавычек, заголовков и пояснений.
""".strip()

    if task == TextGenerationTask.INCIDENT_REPORT:
        return """
Ты формулируешь текст первичного сообщения о происшествии для учебной карточки
диспетчера ДДС Системы-112.

Представь, что оператор во время разговора или сразу после него быстро заносит
полученную информацию в рабочую карточку.

Текст должен выглядеть как реальная короткая операторская запись,
а не как текст, написанный искусственным интеллектом.

СТИЛЬ:
- обычно 1–3 короткие фразы;
- естественный разговорно-служебный язык;
- начинай сразу с сути происшествия или наблюдения;
- допустимы неполные предложения;
- допустимо начало со строчной буквы;
- пунктуация может быть упрощённой;
- не стремись сделать текст литературно идеальным;
- допускаются естественные сокращения обычных слов;
- крайне редко допустима одна лёгкая опечатка или пропущенная буква,
  если это не затрагивает важные данные;
- не делай текст намеренно неграмотным.

Текст НЕ должен выглядеть как:
- официальный отчёт;
- пресс-релиз;
- протокол;
- сводка;
- перечень полей формы;
- художественное описание.

НЕ ИСПОЛЬЗУЙ без необходимости канцелярские зачины:
«Поступило сообщение о...»
«Зафиксировано происшествие...»
«По предварительной информации...»
«По адресу произошло...»
«На месте наблюдается...»
«Имеется информация о...»

Не нужно каждый раз специально писать адрес, название объекта и тип происшествия,
если они уже очевидны из контекста и не нужны для понимания сообщения.

ХОРОШИЙ СТИЛЬ:
«запах гари в коридоре 2 этажа, есть дым, горения пока не видно,
по пострадавшим неизвестно»

«в школе запах гари на 2 этаже, вроде дым из кабинета, пострад пока нет»

«дым на 3 этаже, сильный запах гари, откуда идет пока непонятно»

«из кабинета на втором этаже идет дым, людей внутри не видно»

ПЛОХОЙ СТИЛЬ:
«В образовательном учреждении произошло возгорание.
По предварительной информации наблюдается сильное задымление на втором этаже.
Сведения о пострадавших уточняются.»

ФАКТЫ:
Основные факты происшествия находятся в:
- facts.description;
- facts.caller_text;
- facts.variant_facts;
- facts.additional_conditions.

Каждое условие из facts.additional_conditions должно быть учтено,
если оно присутствует.

Поля facts.title, facts.incident_type, facts.object_name и facts.address
используй как контекст. Не переписывай их механически в текст и не дублируй
уже сказанное.

КРИТИЧЕСКИ ВАЖНО:
- используй только переданные факты;
- не придумывай людей;
- не придумывай очевидцев и заявителей;
- не придумывай адреса;
- не придумывай этажи и помещения;
- не придумывай причину происшествия;
- не придумывай пострадавших;
- не придумывай действия служб;
- не придумывай развитие ситуации;
- не меняй числа;
- не меняй названия объектов и адреса;
- не меняй количество и состояние пострадавших;
- сохраняй степень уверенности: «вроде», «предположительно», «неизвестно»,
  если она есть во входных данных;
- если факт неизвестен, оставь его неизвестным;
- отсутствие сведений НЕ означает отсутствие события.

Верни только готовый текст карточки.
Без заголовка, кавычек, комментариев и пояснений.
""".strip()

    raise ValueError(f"Неизвестный тип генерации текста: {task}")


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
        prompt += (
            "\n\nФормат ответа: обычный текст без Markdown. "
            "Не используй заголовки, списки, выделение звёздочками, "
            "обратные кавычки и блоки кода."
        )
        if (
            request.task == TextGenerationTask.INCIDENT_REPORT
            and request.context
            and request.context.get("previous_text")
        ):
            prompt += (
                " Это повторная генерация. Текст из context.previous_text уже показан "
                "преподавателю. "
                "Сформулируй новую запись заметно иначе. Используй только факты из facts; "
                "previous_text нужен лишь для сравнения формулировок."
            )
        version = PROMPT_VERSIONS[request.task]
        fingerprint = input_hash(request, self.provider.name, self.provider.model)
        started = monotonic()
        result = None
        plain_text = None
        provider_error = False
        if self.enabled and self.provider.name != "template":
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        self.provider.generate(request, prompt), timeout=self.timeout_seconds
                    )
                    plain_text = _plain_text(result.text)
                    _validate_text(plain_text)
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
            plain_text = (
                _plain_text(result.text) if result.provider != "template" else result.text
            )
            _validate_text(plain_text)
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
            text=plain_text,
            provider=result.provider,
            model=result.model,
            prompt_version=version,
            fallback_used=result.fallback_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ).snapshot(fingerprint)
        snapshot["provider_error"] = provider_error
        return snapshot


def _plain_text(value: str) -> str:
    def unwrap(match: re.Match[str]) -> str:
        return next(group for group in match.groups() if group is not None)

    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"`{3,}.*|(?:[-*_]\s*){3,}", line):
            continue
        line = re.sub(r"^#{1,6}\s+|^>\s?", "", line)
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        line = re.sub(
            r"!?\[([^]]+)]\(([^)]+)\)",
            lambda match: (
                match[1] if match[1] == match[2] else f"{match[1]} ({match[2]})"
            ),
            line,
        )
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`", unwrap, line)
        line = re.sub(
            r"(?<!\w)\*([^\s*][^*]*?)\*(?!\w)|(?<!\w)_([^\s_][^_]*?)_(?!\w)",
            unwrap,
            line,
        )
        lines.append(line)
    return "\n".join(lines).strip()


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
