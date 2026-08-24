from unittest.mock import AsyncMock

import pytest

from app.action_agent import (
    _add_comment_impl,
    _add_worklog_impl,
    _build_prompt,
    _get_available_transitions_impl,
    _get_ticket_status_impl,
    _transition_ticket_impl,
)
from app.actions import ActionStepResult
from app.classifier import FeedClassification, Intent, Severity
from app.jira_client import JiraClientError


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.RESOLVED,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key="AIOPS-1",
        title="DB pool exhaustion",
        summary="Connection pool exhausted on payments-svc",
        reasoning="clear signal",
        resolution_comment="Confirmed fixed after deploy",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


@pytest.mark.asyncio
async def test_get_ticket_status_impl_returns_name_and_category():
    jira = AsyncMock()
    jira.get_issue.return_value = {
        "fields": {"status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}}}
    }

    result = await _get_ticket_status_impl(jira, "AIOPS-1")

    jira.get_issue.assert_awaited_once_with("AIOPS-1", fields=["status"])
    assert result == '{"name": "In Progress", "category": "In Progress"}'


@pytest.mark.asyncio
async def test_get_available_transitions_impl_includes_extra_fields():
    jira = AsyncMock()
    jira.get_transitions.return_value = [
        {
            "id": "31",
            "name": "Resolve",
            "to": {"name": "Resolved", "statusCategory": {"name": "Done"}},
            "fields": {
                "customfield_14608": {"schema": {"type": "string"}, "name": "Solution"},
            },
        },
        {
            "id": "51",
            "name": "Withdraw",
            "to": {"name": "Withdrawn", "statusCategory": {"name": "Done"}},
        },
    ]

    result = await _get_available_transitions_impl(jira, "AIOPS-1")

    import json

    parsed = json.loads(result)
    assert [t["name"] for t in parsed] == ["Resolve", "Withdraw"]
    assert parsed[0]["extra_fields"] == [
        {"field_id": "customfield_14608", "label": "Solution", "type": "string"}
    ]
    assert parsed[1]["extra_fields"] == []


@pytest.mark.asyncio
async def test_add_comment_impl_records_success_step():
    jira = AsyncMock()
    steps: list[ActionStepResult] = []

    result = await _add_comment_impl(jira, steps, "AIOPS-1", "Confirmed fixed")

    jira.add_comment.assert_awaited_once_with("AIOPS-1", "Confirmed fixed")
    assert steps == [ActionStepResult(step="comment", ok=True)]
    assert "posted" in result.lower()


@pytest.mark.asyncio
async def test_add_comment_impl_records_failure_step():
    jira = AsyncMock()
    jira.add_comment.side_effect = JiraClientError("Jira 500")
    steps: list[ActionStepResult] = []

    result = await _add_comment_impl(jira, steps, "AIOPS-1", "body")

    assert steps == [ActionStepResult(step="comment", ok=False, error="Jira 500")]
    assert "Jira 500" in result


@pytest.mark.asyncio
async def test_transition_ticket_impl_parses_fields_json_and_records_success():
    jira = AsyncMock()
    steps: list[ActionStepResult] = []

    result = await _transition_ticket_impl(
        jira, steps, "AIOPS-1", "31", fields_json='{"customfield_14608": "fixed"}', comment="note"
    )

    jira.do_transition.assert_awaited_once_with(
        "AIOPS-1", "31", comment="note", fields={"customfield_14608": "fixed"}
    )
    assert steps == [ActionStepResult(step="transition", ok=True)]
    assert "executed" in result.lower()


@pytest.mark.asyncio
async def test_transition_ticket_impl_treats_empty_object_as_no_fields():
    jira = AsyncMock()
    steps: list[ActionStepResult] = []

    await _transition_ticket_impl(jira, steps, "AIOPS-1", "31")

    jira.do_transition.assert_awaited_once_with("AIOPS-1", "31", comment=None, fields=None)


@pytest.mark.asyncio
async def test_transition_ticket_impl_reports_invalid_json_without_calling_jira():
    jira = AsyncMock()
    steps: list[ActionStepResult] = []

    result = await _transition_ticket_impl(jira, steps, "AIOPS-1", "31", fields_json="not json")

    jira.do_transition.assert_not_awaited()
    assert steps == []
    assert "not valid JSON" in result


@pytest.mark.asyncio
async def test_transition_ticket_impl_records_failure_step():
    jira = AsyncMock()
    jira.do_transition.side_effect = JiraClientError("No transition to 'Resolved' found")
    steps: list[ActionStepResult] = []

    result = await _transition_ticket_impl(jira, steps, "AIOPS-1", "31")

    assert steps == [
        ActionStepResult(step="transition", ok=False, error="No transition to 'Resolved' found")
    ]
    assert "Failed to transition" in result


@pytest.mark.asyncio
async def test_add_worklog_impl_records_success_step():
    jira = AsyncMock()
    steps: list[ActionStepResult] = []

    await _add_worklog_impl(jira, steps, "AIOPS-1", "5m", "AI-triaged resolution")

    jira.add_worklog.assert_awaited_once_with("AIOPS-1", "5m", "AI-triaged resolution")
    assert steps == [ActionStepResult(step="worklog", ok=True)]


@pytest.mark.asyncio
async def test_add_worklog_impl_records_failure_step():
    jira = AsyncMock()
    jira.add_worklog.side_effect = JiraClientError("permission denied")
    steps: list[ActionStepResult] = []

    await _add_worklog_impl(jira, steps, "AIOPS-1", "5m", "note")

    assert steps == [ActionStepResult(step="worklog", ok=False, error="permission denied")]


def test_build_prompt_uses_resolution_comment_when_present():
    prompt = _build_prompt(_classification(resolution_comment="Confirmed fixed after deploy"), "AIOPS-1")

    assert "AIOPS-1" in prompt
    assert "Confirmed fixed after deploy" in prompt


def test_build_prompt_falls_back_to_summary_when_no_resolution_comment():
    prompt = _build_prompt(
        _classification(resolution_comment=None, summary="Issue no longer reproducing"), "AIOPS-1"
    )

    assert "Issue no longer reproducing" in prompt
