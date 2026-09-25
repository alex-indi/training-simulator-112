"""Opt-in live provider check; never runs in ordinary CI."""

import asyncio
import os

import pytest

from app.core.config import get_settings
from app.services.text_generation.renderer import (
    TextGenerationRequest,
    TextGenerationTask,
    get_renderer,
)


@pytest.mark.skipif(
    os.getenv("RUN_AI_INTEGRATION_TESTS", "false").lower() != "true",
    reason="Live AI integration is opt-in",
)
def test_live_ai_text_rendering():
    settings = get_settings()
    if not settings.ai_text_enabled or not settings.ai_text_model:
        pytest.skip("Enable AI_TEXT and select a model first")

    async def run():
        result = await get_renderer(settings).render(
            TextGenerationRequest(
                task=TextGenerationTask.RESPONSE_MESSAGE,
                facts={"description": "Группа прибыла к месту"},
            )
        )
        assert result["rendered_text"]
        assert not result["fallback_used"], "Live provider was not available"

    asyncio.run(run())
