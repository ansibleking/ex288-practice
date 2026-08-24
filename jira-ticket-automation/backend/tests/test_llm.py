import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings
from app.llm import AnthropicStructuredClient, OnPremStructuredClient, get_llm_client
from app.llm.onprem_client import OnPremLLMError


def _settings(**overrides) -> Settings:
    defaults = dict(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _classification() -> FeedClassification:
    return FeedClassification(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.HIGH,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Connection pool exhausted",
        reasoning="Clear signal",
    )


def test_get_llm_client_returns_anthropic_client_by_default():
    client = get_llm_client(_settings(anthropic_api_key="key", default_llm_provider="anthropic"))
    assert isinstance(client, AnthropicStructuredClient)


def test_get_llm_client_returns_onprem_client():
    client = get_llm_client(
        _settings(default_llm_provider="onprem", onprem_llm_base_url="http://onprem.example/v1")
    )
    assert isinstance(client, OnPremStructuredClient)


def test_get_llm_client_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="onprem"):
        get_llm_client(_settings(default_llm_provider="bogus"))


def test_onprem_client_defaults_to_verifying_ssl(monkeypatch):
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)

    OnPremStructuredClient(
        _settings(default_llm_provider="onprem", onprem_llm_base_url="http://onprem.example/v1")
    )
    assert captured["verify"] is True


def test_onprem_client_can_disable_ssl_verification(monkeypatch):
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)

    OnPremStructuredClient(
        _settings(
            default_llm_provider="onprem",
            onprem_llm_base_url="http://onprem.example/v1",
            default_llm_verify_ssl=False,
        )
    )
    assert captured["verify"] is False


@pytest.mark.asyncio
async def test_anthropic_client_returns_parsed_output():
    parsed = _classification()
    raw_client = AsyncMock()
    raw_client.messages.parse.return_value = SimpleNamespace(parsed_output=parsed, stop_reason="end_turn")

    client = AnthropicStructuredClient(
        _settings(default_llm_model="claude-opus-5"), client=raw_client
    )
    result = await client.parse(system="sys", user_content="hello", output_model=FeedClassification)

    assert result is parsed
    call_kwargs = raw_client.messages.parse.await_args.kwargs
    assert call_kwargs["model"] == "claude-opus-5"
    assert call_kwargs["output_format"] is FeedClassification


@pytest.mark.asyncio
async def test_anthropic_client_raises_when_no_parsed_output():
    raw_client = AsyncMock()
    raw_client.messages.parse.return_value = SimpleNamespace(parsed_output=None, stop_reason="refusal")
    client = AnthropicStructuredClient(_settings(), client=raw_client)

    with pytest.raises(ValueError, match="refusal"):
        await client.parse(system="sys", user_content="hello", output_model=FeedClassification)


@pytest.mark.asyncio
async def test_onprem_client_parses_structured_response():
    settings = _settings(
        default_llm_provider="onprem",
        default_llm_model="qwen/qwen3.5-122b-a10b",
        onprem_llm_base_url="http://onprem.example/v1",
        onprem_llm_api_key="secret-key",
    )
    parsed = _classification()

    with respx.mock(base_url="http://onprem.example") as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": parsed.model_dump_json()}}]},
            )
        )

        client = OnPremStructuredClient(settings)
        try:
            result = await client.parse(system="sys", user_content="hello", output_model=FeedClassification)
        finally:
            await client.aclose()

    assert result == parsed
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer secret-key"
    sent = json.loads(request.content)
    assert sent["model"] == "qwen/qwen3.5-122b-a10b"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["name"] == "FeedClassification"


@pytest.mark.asyncio
async def test_onprem_client_raises_on_http_error():
    settings = _settings(
        default_llm_provider="onprem", onprem_llm_base_url="http://onprem.example/v1"
    )
    with respx.mock(base_url="http://onprem.example") as mock:
        mock.post("/v1/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
        client = OnPremStructuredClient(settings)
        try:
            with pytest.raises(OnPremLLMError, match="500"):
                await client.parse(system="sys", user_content="hi", output_model=FeedClassification)
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_onprem_client_raises_on_malformed_response():
    settings = _settings(
        default_llm_provider="onprem", onprem_llm_base_url="http://onprem.example/v1"
    )
    with respx.mock(base_url="http://onprem.example") as mock:
        mock.post("/v1/chat/completions").mock(return_value=httpx.Response(200, json={"unexpected": True}))
        client = OnPremStructuredClient(settings)
        try:
            with pytest.raises(OnPremLLMError, match="missing choices"):
                await client.parse(system="sys", user_content="hi", output_model=FeedClassification)
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_onprem_client_raises_on_schema_mismatch():
    settings = _settings(
        default_llm_provider="onprem", onprem_llm_base_url="http://onprem.example/v1"
    )
    with respx.mock(base_url="http://onprem.example") as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"content": '{"not": "the schema"}'}}]}
            )
        )
        client = OnPremStructuredClient(settings)
        try:
            with pytest.raises(OnPremLLMError, match="did not match"):
                await client.parse(system="sys", user_content="hi", output_model=FeedClassification)
        finally:
            await client.aclose()
