from __future__ import annotations

import anthropic
from pydantic import BaseModel

from app.config import Settings


class AnthropicStructuredClient:
    """Structured-output client backed by the Anthropic Messages API."""

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.default_llm_model

    async def aclose(self) -> None:
        await self._client.close()

    async def parse(self, *, system: str, user_content: str, output_model: type[BaseModel]) -> BaseModel:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_format=output_model,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(f"Classification did not return parsed output (stop_reason={response.stop_reason})")
        return parsed
