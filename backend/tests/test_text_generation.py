"""AI text preparation remains portable and works without an external service."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx

from app.core.config import Settings
from app.modules.admin.models import AIProviderConfig
from app.services.text_generation.providers import (
    OpenAICompatibleProvider,
    OpenAIProvider,
    create_provider,
)
from app.services.text_generation.renderer import (
    AITextRenderer,
    ProviderHealth,
    TextGenerationRequest,
    TextGenerationResult,
    TextGenerationTask,
    renderer_for_database,
)


class FakeProvider:
    name = "fake_local"
    model = "local-test"

    def __init__(self, text="Группа прибыла.", delay=0):
        self.text = text
        self.delay = delay
        self.calls = 0

    async def generate(self, request, prompt):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.text, Exception):
            raise self.text
        return TextGenerationResult(text=self.text, provider=self.name, model=self.model)

    async def healthcheck(self):
        return ProviderHealth("AVAILABLE", self.name, self.model)


def test_renderer_keeps_facts_and_uses_fallback_for_error_timeout_and_bad_output():
    facts = {"description": "Бригада прибыла", "title": "Прибытие"}
    request = TextGenerationRequest(TextGenerationTask.RESPONSE_MESSAGE, facts)

    async def run():
        success = FakeProvider()
        rendered = await AITextRenderer(success).render(request)
        assert rendered["rendered_text"] == "Группа прибыла."
        assert rendered["prompt_version"] == "response_crew_message_v2"
        assert rendered["input_hash"] and not rendered["fallback_used"]
        assert success.calls == 1
        assert facts == {"description": "Бригада прибыла", "title": "Прибытие"}
        for failing in (
            FakeProvider(ValueError("offline")),
            FakeProvider(""),
            FakeProvider(delay=0.02),
        ):
            fallback = await AITextRenderer(failing, timeout_seconds=0.001).render(request)
            assert fallback["rendered_text"] == "Бригада прибыла"
            assert fallback["provider"] == "template"
            assert fallback["fallback_used"]
            assert failing.calls == 2
        disabled = await AITextRenderer(FakeProvider(), enabled=False).render(request)
        assert disabled["provider"] == "template"

    asyncio.run(run())


def test_incident_report_keeps_source_facts_in_offline_mode():
    facts = {
        "description": "Очевидец сообщил о задымлении.",
        "caller_text": "Сведения о пострадавших отсутствуют.",
        "incident_type": "Пожар",
    }

    async def run():
        result = await AITextRenderer(FakeProvider(), enabled=False).render(
            TextGenerationRequest(TextGenerationTask.INCIDENT_REPORT, facts)
        )
        assert result["rendered_text"] == (
            "Очевидец сообщил о задымлении.\nСведения о пострадавших отсутствуют."
        )
        assert result["prompt_version"] == "incident_operator_entry_v2"
        assert facts["incident_type"] == "Пожар"

    asyncio.run(run())


def test_school_fire_fallback_is_short_and_keeps_variant_facts():
    variant = {
        "floor": 2,
        "room": "коридор",
        "observation": "сильное задымление",
        "casualties": "пострадавшие неизвестны",
    }
    request = TextGenerationRequest(
        TextGenerationTask.INCIDENT_REPORT,
        {"description": "Служебное описание", "caller_text": "", "variant_facts": variant},
    )

    async def run():
        result = await AITextRenderer(FakeProvider(), enabled=False).render(request)
        text = result["rendered_text"]
        assert text == (
            "сильное задымление на 2 этаже школы, коридор; пострадавшие неизвестны"
        )
        assert "Зафиксировано происшествие" not in text
        assert "Служебное описание" not in text

    asyncio.run(run())


def test_explicit_admin_configuration_selects_local_provider():
    settings = Settings(database_url="sqlite://", ai_text_enabled=False)
    database = AsyncMock()
    database.get.return_value = AIProviderConfig(
        id=1,
        provider="OPENAI_COMPATIBLE",
        model="qwen-local",
        base_url="http://local.test/v1",
        enabled=True,
        timeout_seconds=7,
    )

    async def run():
        renderer = await renderer_for_database(database, settings)
        assert renderer.enabled
        assert renderer.provider.name == "openai_compatible"
        assert renderer.provider.model == "qwen-local"
        assert renderer.provider.base_url == "http://local.test/v1"
        assert renderer.timeout_seconds == 7

    asyncio.run(run())


def test_config_factory_and_compatible_http_contract_without_network():
    base = Settings(database_url="sqlite://", ai_text_enabled=True, ai_text_model="local-test")
    assert isinstance(
        create_provider(base.model_copy(update={"ai_text_provider": "openai"})), OpenAIProvider
    )
    assert isinstance(
        create_provider(base.model_copy(update={"ai_text_provider": "openai_compatible"})),
        OpenAICompatibleProvider,
    )
    assert create_provider(base.model_copy(update={"ai_text_enabled": False})).name == "template"
    requests = []

    def respond(request: httpx.Request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Прибыли к месту."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    async def run():
        provider = OpenAICompatibleProvider(
            base_url="http://local.test/v1",
            model="local-test",
            api_key="local-secret",
            transport=httpx.MockTransport(respond),
        )
        request = TextGenerationRequest(
            TextGenerationTask.RESPONSE_MESSAGE, {"description": "Бригада прибыла"}
        )
        result = await AITextRenderer(provider).render(request)
        assert result["rendered_text"] == "Прибыли к месту."
        assert result["input_tokens"] == 12 and result["output_tokens"] == 5
        assert result["model"] == "local-test"
        assert (await provider.healthcheck()).status == "AVAILABLE"
        assert requests[0].url.path == "/v1/chat/completions"
        sent = json.loads(requests[0].content)
        assert sent["model"] == "local-test" and sent["max_tokens"] == 300
        assert requests[0].headers["authorization"] == "Bearer local-secret"
        assert requests[1].url.path == "/v1/models"
        assert "local-secret" not in json.dumps(result)

    asyncio.run(run())
