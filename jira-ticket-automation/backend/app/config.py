from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Jira Data Center connection
    jira_base_url: str
    jira_pat: str
    jira_managed_label: str = "aiops-managed"
    jira_project_key: str
    jira_issue_type: str = "Task"
    jira_resolved_transition_name: str = "Resolved"
    # Some Jira permission schemes/issue security levels deny "Log Work" to
    # the service account regardless of project role or assignment (seen on
    # this instance -- confirmed via /mypermissions on multiple assigned,
    # open tickets). When that's the case, set this False so the app stops
    # attempting a call that can never succeed; log-work updates fall back
    # to a comment instead, which the account can post.
    jira_worklog_enabled: bool = True
    # Some workflows' terminal "Resolve" transition requires a text field
    # (e.g. "Solution") on its screen -- discovered the same way as other
    # required-but-unlisted fields on this instance, via a 400 on the
    # transition attempt. When set, auto-resolve fills it with the
    # classification's resolution_comment (falling back to summary), since
    # that's exactly what a "Solution" field is for. Leave empty if your
    # resolve transition doesn't need this.
    jira_resolution_field_id: str = ""
    request_timeout_seconds: float = 15.0

    # Extra fields merged into every issue-creation payload, for projects
    # that require custom fields beyond summary/description/labels (e.g. a
    # JSM "Reporting Service" field). JSON object, e.g.:
    # JIRA_EXTRA_CREATE_FIELDS={"customfield_14503": {"value": "IT Infrastructure"}}
    jira_extra_create_fields: dict[str, Any] = {}

    # Insight/Assets object-reference field (e.g. "Reporting Service"), for
    # Jira instances using the Riada Insight plugin where a custom field's
    # value must reference a catalog object rather than a plain string.
    # Leave jira_reporting_service_field_id empty to disable this entirely.
    jira_reporting_service_field_id: str = ""
    jira_reporting_service_object_type: str = "Service"
    jira_insight_object_schema_id: int = 1

    # Extra required plain-select fields (beyond issue type and reporting
    # service), discovered dynamically rather than hardcoded -- Jira DC has
    # no working createmeta on this instance, so option lists are read from
    # a known-good existing issue's editmeta instead. JSON object mapping
    # field id -> display label, e.g.:
    # JIRA_EXTRA_SELECT_FIELDS={"customfield_36200": "Subsidiary", "customfield_32404": "SR Type"}
    jira_field_metadata_reference_issue: str = ""
    jira_extra_select_fields: dict[str, str] = {}

    # Custom user/group-picker fields that also make someone an approver on
    # a ticket, beyond plain assignment -- e.g. this instance's IT Change
    # workflow grants Approve/Reject to whoever is named in "IMD Domain
    # Approvers" (customfield_25502), even when the ticket itself is
    # unassigned. Discovered one at a time the same way as
    # jira_extra_select_fields; the approvals list ORs these into its
    # candidate search (JSON array of field ids), e.g.:
    # JIRA_APPROVER_FIELDS=["customfield_25502"]
    jira_approver_fields: list[str] = []

    # LLM provider selection -- "anthropic" or "onprem". default_llm_model is
    # interpreted by whichever provider is active (an Anthropic model id like
    # "claude-opus-5", or an on-prem model id like "qwen/qwen3.5-122b-a10b").
    default_llm_provider: str = "anthropic"
    default_llm_model: str = "claude-opus-5"

    # Anthropic
    anthropic_api_key: str = ""

    # On-prem, OpenAI-compatible endpoint (e.g. vLLM's /v1/chat/completions
    # with response_format json_schema guided decoding).
    onprem_llm_base_url: str = ""
    onprem_llm_api_key: str = ""
    default_llm_verify_ssl: bool = True

    # Agentic action execution (resolve): independent of default_llm_provider
    # above, since Anthropic's Tool Runner (client.beta.messages.tool_runner)
    # has no equivalent for self-hosted OpenAI-compatible endpoints -- it's
    # Anthropic-API-only. Classification keeps using default_llm_provider
    # unchanged; only the resolve-execution step uses this model, and only
    # when anthropic_api_key is set. With no key configured, resolve falls
    # back to the deterministic (non-agentic) path automatically.
    agent_model: str = "claude-opus-5"

    # Autonomy thresholds -- starting guesses, tune after real usage
    autonomy_auto_confidence_min: float = 0.85
    autonomy_auto_severity_max: str = "medium"
    autonomy_update_confidence_min: float = 0.7

    # Storage
    database_path: str = "data/audit.db"

    # Scheduler -- background loop polling interval for due create/resolve items
    scheduler_poll_seconds: float = 30.0

    @property
    def llm_configured(self) -> bool:
        if self.default_llm_provider.lower() == "onprem":
            return bool(self.onprem_llm_base_url)
        return bool(self.anthropic_api_key)

    @property
    def reporting_service_configured(self) -> bool:
        return bool(self.jira_reporting_service_field_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
