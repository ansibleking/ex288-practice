from __future__ import annotations

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings


class OnPremLLMError(RuntimeError):
    """Raised when the on-prem OpenAI-compatible endpoint returns an unexpected response."""


class OnPremStructuredClient:
    """Structured-output client for a self-hosted OpenAI-compatible endpoint (e.g. vLLM).

    Uses the OpenAI Chat Completions request shape with response_format
    json_schema (vLLM's guided-decoding integration) rather than the openai
    SDK, since only a single endpoint call is needed here.
    """

    def __init__(self, settings: Settings, timeout: float | None = None):
        base_url = settings.onprem_llm_base_url.rstrip("/")
        headers = {}
        if settings.onprem_llm_api_key:
            headers["Authorization"] = f"Bearer {settings.onprem_llm_api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            # request_timeout_seconds is tuned for fast REST/classification
            # calls; callers doing heavier generation (e.g. extracting a
            # network diagram from dozens of sheet rows) pass an explicit,
            # more generous timeout instead of inheriting that default.
            timeout=timeout if timeout is not None else settings.request_timeout_seconds,
            verify=settings.default_llm_verify_ssl,
        )
        self._model = settings.default_llm_model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def parse(self, *, system: str, user_content: str, output_model: type[BaseModel]) -> BaseModel:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "schema": output_model.model_json_schema(),
                    "strict": True,
                },
            },
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            # Some httpx exceptions (e.g. a bare ReadTimeout) stringify to an
            # empty message -- repr() always includes the exception type so
            # a timeout doesn't show up as a blank, undiagnosable error.
            raise OnPremLLMError(f"On-prem LLM endpoint unreachable: {exc!r}") from exc
        if response.is_error:
            raise OnPremLLMError(
                f"On-prem LLM endpoint returned {response.status_code}: {response.text[:500]}"
            )

        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OnPremLLMError(f"On-prem LLM response missing choices[0].message.content: {body!r}") from exc

        try:
            return output_model.model_validate_json(content)
        except ValidationError as exc:
            raise OnPremLLMError(f"On-prem LLM response did not match the expected schema: {exc}") from exc
