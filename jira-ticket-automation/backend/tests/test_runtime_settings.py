import pytest

from app.config import Settings
from app.runtime_settings import effective_provider, get_provider_override, set_provider_override


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        database_path=str(tmp_path / "audit.db"),
        default_llm_provider="onprem",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_get_provider_override_returns_none_when_never_set(tmp_path):
    assert get_provider_override(_settings(tmp_path)) is None


def test_set_and_get_provider_override_round_trips(tmp_path):
    settings = _settings(tmp_path)

    set_provider_override(settings, "anthropic")

    assert get_provider_override(settings) == "anthropic"


def test_set_provider_override_none_clears_it(tmp_path):
    settings = _settings(tmp_path)
    set_provider_override(settings, "anthropic")

    set_provider_override(settings, None)

    assert get_provider_override(settings) is None


def test_set_provider_override_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError, match="onprem"):
        set_provider_override(_settings(tmp_path), "bogus")


def test_effective_provider_falls_back_to_default_when_no_override(tmp_path):
    settings = _settings(tmp_path, default_llm_provider="onprem")

    assert effective_provider(settings) == "onprem"


def test_effective_provider_prefers_override_over_default(tmp_path):
    settings = _settings(tmp_path, default_llm_provider="onprem")
    set_provider_override(settings, "anthropic")

    assert effective_provider(settings) == "anthropic"


def test_override_persists_across_settings_instances_pointing_at_same_data_dir(tmp_path):
    settings_a = _settings(tmp_path)
    set_provider_override(settings_a, "anthropic")

    settings_b = _settings(tmp_path)

    assert get_provider_override(settings_b) == "anthropic"
