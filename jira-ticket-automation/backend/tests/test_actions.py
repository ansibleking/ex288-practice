from unittest.mock import AsyncMock

import pytest

from app.actions import ActionResult, ActionStepResult, ActionType, action_type_for, execute_action, is_auto
from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings
from app.jira_client import JiraClientError
from app.routing import RoutingDecision


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        jira_issue_type="Task",
        jira_managed_label="aiops-managed",
        jira_resolved_transition_name="Resolved",
        # No anthropic_api_key: these tests exercise the deterministic resolve
        # path. Agentic-dispatch behavior has its own tests further down.
    )


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Seeing intermittent 503s",
        reasoning="clear signal",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


def test_action_type_for_maps_every_decision():
    assert action_type_for(RoutingDecision.AUTO_CREATE) is ActionType.CREATE
    assert action_type_for(RoutingDecision.PROPOSE_CREATE) is ActionType.CREATE
    assert action_type_for(RoutingDecision.AUTO_LOG_WORK) is ActionType.LOG_WORK
    assert action_type_for(RoutingDecision.AUTO_RESOLVE) is ActionType.RESOLVE
    assert action_type_for(RoutingDecision.PROPOSE_RESOLVE) is ActionType.RESOLVE
    assert action_type_for(RoutingDecision.SKIP_AS_NOISE) is ActionType.NONE


def test_is_auto_distinguishes_auto_from_propose():
    assert is_auto(RoutingDecision.AUTO_CREATE)
    assert is_auto(RoutingDecision.AUTO_LOG_WORK)
    assert is_auto(RoutingDecision.AUTO_RESOLVE)
    assert not is_auto(RoutingDecision.PROPOSE_CREATE)
    assert not is_auto(RoutingDecision.PROPOSE_RESOLVE)
    assert not is_auto(RoutingDecision.SKIP_AS_NOISE)


@pytest.mark.asyncio
async def test_execute_create_success():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-42"}
    classification = _classification()

    result = await execute_action(ActionType.CREATE, classification, jira, _settings())

    assert result.jira_issue_key == "AIOPS-42"
    assert result.all_ok
    jira.create_issue.assert_awaited_once_with(
        project_key="AIOPS",
        issue_type="Task",
        summary="DB pool exhaustion",
        description="Seeing intermittent 503s",
        labels=["aiops-managed"],
        extra_fields=None,
    )


@pytest.mark.asyncio
async def test_execute_create_uses_issue_type_override_when_given():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-43"}
    classification = _classification()

    await execute_action(ActionType.CREATE, classification, jira, _settings(), issue_type="Service Request")

    jira.create_issue.assert_awaited_once_with(
        project_key="AIOPS",
        issue_type="Service Request",
        summary="DB pool exhaustion",
        description="Seeing intermittent 503s",
        labels=["aiops-managed"],
        extra_fields=None,
    )


@pytest.mark.asyncio
async def test_execute_create_passes_configured_extra_fields():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-44"}
    classification = _classification()
    settings = _settings().model_copy(
        update={"jira_extra_create_fields": {"customfield_14503": {"value": "IT Infrastructure"}}}
    )

    await execute_action(ActionType.CREATE, classification, jira, settings)

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_14503": {"value": "IT Infrastructure"}}


@pytest.mark.asyncio
async def test_execute_create_wraps_reporting_service_key_as_insight_reference():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-45"}
    classification = _classification()
    settings = _settings().model_copy(update={"jira_reporting_service_field_id": "customfield_14503"})

    await execute_action(
        ActionType.CREATE, classification, jira, settings, reporting_service_key="SD-1179"
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_14503": [{"key": "SD-1179"}]}


@pytest.mark.asyncio
async def test_execute_create_ignores_reporting_service_key_when_field_not_configured():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-46"}
    classification = _classification()

    await execute_action(
        ActionType.CREATE, classification, jira, _settings(), reporting_service_key="SD-1179"
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] is None


@pytest.mark.asyncio
async def test_execute_create_merges_static_extra_fields_with_reporting_service():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-47"}
    classification = _classification()
    settings = _settings().model_copy(
        update={
            "jira_reporting_service_field_id": "customfield_14503",
            "jira_extra_create_fields": {"customfield_99999": "other"},
        }
    )

    await execute_action(
        ActionType.CREATE, classification, jira, settings, reporting_service_key="SD-1179"
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {
        "customfield_99999": "other",
        "customfield_14503": [{"key": "SD-1179"}],
    }


@pytest.mark.asyncio
async def test_execute_create_includes_configured_extra_select_field_values():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-48"}
    classification = _classification()
    settings = _settings().model_copy(
        update={"jira_extra_select_fields": {"customfield_36200": "Subsidiary", "customfield_32404": "SR Type"}}
    )

    await execute_action(
        ActionType.CREATE,
        classification,
        jira,
        settings,
        extra_field_values={"customfield_36200": "43503", "customfield_32404": "38124"},
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {
        "customfield_36200": {"id": "43503"},
        "customfield_32404": {"id": "38124"},
    }


@pytest.mark.asyncio
async def test_execute_create_ignores_extra_field_values_not_in_configured_set():
    jira = AsyncMock()
    jira.create_issue.return_value = {"key": "AIOPS-49"}
    classification = _classification()
    settings = _settings().model_copy(update={"jira_extra_select_fields": {"customfield_36200": "Subsidiary"}})

    await execute_action(
        ActionType.CREATE,
        classification,
        jira,
        settings,
        extra_field_values={"customfield_99999": "1"},
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] is None


@pytest.mark.asyncio
async def test_execute_create_failure_reports_step_error():
    jira = AsyncMock()
    jira.create_issue.side_effect = JiraClientError("Jira 500")
    classification = _classification()

    result = await execute_action(ActionType.CREATE, classification, jira, _settings())

    assert result.jira_issue_key is None
    assert not result.all_ok
    assert result.steps[0].step == "create"
    assert "Jira 500" in result.steps[0].error


@pytest.mark.asyncio
async def test_execute_log_work_calls_worklog_with_matched_key():
    jira = AsyncMock()
    classification = _classification(
        intent=Intent.UPDATE_EXISTING, matched_ticket_key="AIOPS-1", summary="More detail arrived"
    )

    result = await execute_action(ActionType.LOG_WORK, classification, jira, _settings())

    assert result.jira_issue_key == "AIOPS-1"
    assert result.all_ok
    jira.add_worklog.assert_awaited_once_with("AIOPS-1", "5m", "More detail arrived")


@pytest.mark.asyncio
async def test_execute_log_work_falls_back_to_comment_when_worklog_disabled():
    jira = AsyncMock()
    classification = _classification(
        intent=Intent.UPDATE_EXISTING, matched_ticket_key="AIOPS-1", summary="More detail arrived"
    )
    settings = _settings().model_copy(update={"jira_worklog_enabled": False})

    result = await execute_action(ActionType.LOG_WORK, classification, jira, settings)

    assert result.jira_issue_key == "AIOPS-1"
    assert result.all_ok
    assert result.steps == [ActionStepResult(step="comment", ok=True)]
    jira.add_comment.assert_awaited_once_with("AIOPS-1", "More detail arrived")
    jira.add_worklog.assert_not_awaited()


OPEN_ISSUE = {"fields": {"status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}}}}
CLOSED_ISSUE = {"fields": {"status": {"name": "Withdrawn", "statusCategory": {"name": "Done"}}}}


def _transition(id_: str, name: str, to_name: str, to_category: str) -> dict:
    return {"id": id_, "name": name, "to": {"name": to_name, "statusCategory": {"name": to_category}}}


@pytest.mark.asyncio
async def test_execute_resolve_runs_comment_worklog_transition_in_order():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED,
        matched_ticket_key="AIOPS-1",
        resolution_comment="Confirmed fixed after deploy",
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    assert result.jira_issue_key == "AIOPS-1"
    assert result.all_ok
    assert [s.step for s in result.steps] == ["comment", "worklog", "transition"]
    jira.add_comment.assert_awaited_once_with("AIOPS-1", "Confirmed fixed after deploy")
    jira.do_transition.assert_awaited_once_with("AIOPS-1", "31", fields=None)


@pytest.mark.asyncio
async def test_execute_resolve_falls_back_to_summary_when_no_resolution_comment():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED,
        matched_ticket_key="AIOPS-1",
        summary="Issue no longer reproducing",
        resolution_comment=None,
    )

    await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    jira.add_comment.assert_awaited_once_with("AIOPS-1", "Issue no longer reproducing")


@pytest.mark.asyncio
async def test_execute_resolve_partial_failure_still_records_earlier_successes():
    # comment succeeds, worklog succeeds, transition fails -- all three
    # outcomes must be visible, not just the last one.
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.side_effect = JiraClientError("transitions endpoint down")
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    assert not result.all_ok
    by_step = {s.step: s for s in result.steps}
    assert by_step["comment"].ok is True
    assert by_step["worklog"].ok is True
    assert by_step["transition"].ok is False
    assert "transitions endpoint down" in by_step["transition"].error


@pytest.mark.asyncio
async def test_execute_resolve_reports_missing_transition_as_a_step_error():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = []  # no transitions available at all
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    by_step = {s.step: s for s in result.steps}
    assert by_step["transition"].ok is False
    assert "Resolved" in by_step["transition"].error
    jira.do_transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_resolve_walks_multiple_hops_to_reach_target_status():
    # Open -> Assigned -> Resolved: no direct transition from Open, but a
    # single unambiguous forward candidate at each hop.
    jira = AsyncMock()
    jira.get_issue.return_value = {"fields": {"status": {"name": "Open", "statusCategory": {"name": "To Do"}}}}
    jira.get_transitions.side_effect = [
        [
            _transition("51", "Withdraw", "Withdrawn", "Done"),  # alternate terminal -- must be excluded
            _transition("91", "Change Priority", "Open", "To Do"),  # self-loop -- must be excluded
            _transition("11", "Assign", "Assigned", "To Do"),
        ],
        [_transition("31", "Resolve", "Resolved", "Done")],
    ]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    assert result.all_ok
    assert jira.do_transition.await_args_list == [
        (("AIOPS-1", "11"),),
        (("AIOPS-1", "31"), {"fields": None}),
    ]


@pytest.mark.asyncio
async def test_execute_resolve_stops_when_multiple_forward_candidates_are_ambiguous():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [
        _transition("11", "Assign", "Assigned", "To Do"),
        _transition("21", "Escalate", "Escalated", "In Progress"),
    ]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    by_step = {s.step: s for s in result.steps}
    assert by_step["transition"].ok is False
    assert "Resolved" in by_step["transition"].error
    jira.do_transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_resolve_skips_worklog_and_transition_when_issue_already_closed():
    jira = AsyncMock()
    jira.get_issue.return_value = CLOSED_ISSUE
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    assert result.all_ok
    by_step = {s.step: s for s in result.steps}
    assert by_step["comment"].ok is True
    assert by_step["worklog"].ok is True
    assert by_step["transition"].ok is True
    jira.add_worklog.assert_not_awaited()
    jira.get_transitions.assert_not_awaited()
    jira.do_transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_resolve_proceeds_normally_when_status_lookup_fails():
    jira = AsyncMock()
    jira.get_issue.side_effect = JiraClientError("status lookup unreachable")
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, _settings())

    assert result.all_ok
    jira.add_worklog.assert_awaited_once()
    jira.do_transition.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_resolve_fills_configured_resolution_field_with_resolution_comment():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED,
        matched_ticket_key="AIOPS-1",
        resolution_comment="Confirmed fixed after deploy",
    )
    settings = _settings().model_copy(update={"jira_resolution_field_id": "customfield_14608"})

    result = await execute_action(ActionType.RESOLVE, classification, jira, settings)

    assert result.all_ok
    jira.do_transition.assert_awaited_once_with(
        "AIOPS-1", "31", fields={"customfield_14608": "Confirmed fixed after deploy"}
    )


@pytest.mark.asyncio
async def test_execute_resolve_does_not_fill_resolution_field_on_intermediate_hops():
    # Open -> Assigned -> Resolved: the resolution field must only be
    # attached to the final transition that actually lands on Resolved.
    jira = AsyncMock()
    jira.get_issue.return_value = {
        "fields": {"status": {"name": "Open", "statusCategory": {"name": "To Do"}}}
    }
    jira.get_transitions.side_effect = [
        [_transition("11", "Assign", "Assigned", "To Do")],
        [_transition("31", "Resolve", "Resolved", "Done")],
    ]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )
    settings = _settings().model_copy(update={"jira_resolution_field_id": "customfield_14608"})

    await execute_action(ActionType.RESOLVE, classification, jira, settings)

    assert jira.do_transition.await_args_list == [
        (("AIOPS-1", "11"),),
        (("AIOPS-1", "31"), {"fields": {"customfield_14608": "fixed"}}),
    ]


@pytest.mark.asyncio
async def test_execute_resolve_skips_worklog_when_disabled_but_still_transitions():
    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )
    settings = _settings().model_copy(update={"jira_worklog_enabled": False})

    result = await execute_action(ActionType.RESOLVE, classification, jira, settings)

    assert result.all_ok
    by_step = {s.step: s for s in result.steps}
    assert by_step["worklog"].ok is True
    assert by_step["transition"].ok is True
    jira.add_worklog.assert_not_awaited()
    jira.do_transition.assert_awaited_once_with("AIOPS-1", "31", fields=None)


@pytest.mark.asyncio
async def test_execute_none_action_type_is_a_no_op():
    jira = AsyncMock()
    classification = _classification(intent=Intent.NOISE)

    result = await execute_action(ActionType.NONE, classification, jira, _settings())

    assert result.jira_issue_key is None
    assert result.steps == []
    jira.create_issue.assert_not_awaited()
    jira.add_comment.assert_not_awaited()
    jira.add_worklog.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_resolve_uses_deterministic_path_when_no_anthropic_key(monkeypatch):
    import app.action_agent

    agent_mock = AsyncMock()
    monkeypatch.setattr(app.action_agent, "run_resolve_agent", agent_mock)

    jira = AsyncMock()
    jira.get_issue.return_value = OPEN_ISSUE
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Resolved", "Done")]
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )
    settings = _settings().model_copy(update={"anthropic_api_key": ""})

    result = await execute_action(ActionType.RESOLVE, classification, jira, settings)

    agent_mock.assert_not_awaited()
    assert result.all_ok
    jira.add_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_resolve_uses_agent_path_when_anthropic_key_configured(monkeypatch):
    import app.action_agent

    agent_result = ActionResult(action_type=ActionType.RESOLVE, jira_issue_key="AIOPS-1", steps=[])
    agent_mock = AsyncMock(return_value=agent_result)
    monkeypatch.setattr(app.action_agent, "run_resolve_agent", agent_mock)

    jira = AsyncMock()
    classification = _classification(
        intent=Intent.RESOLVED, matched_ticket_key="AIOPS-1", resolution_comment="fixed"
    )
    settings = _settings().model_copy(update={"anthropic_api_key": "sk-test-key"})

    result = await execute_action(ActionType.RESOLVE, classification, jira, settings)

    agent_mock.assert_awaited_once_with(classification, jira, settings)
    assert result is agent_result
    jira.get_issue.assert_not_awaited()
    jira.add_comment.assert_not_awaited()
