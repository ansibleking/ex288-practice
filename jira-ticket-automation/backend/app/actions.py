from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.classifier import FeedClassification
from app.config import Settings
from app.jira_client import JiraClient, JiraClientError
from app.routing import RoutingDecision

# Placeholder value for auto-logged AI actions -- revisit once real usage
# shows what's representative of the actual triage effort.
WORKLOG_TIME_SPENT = "5m"

# Upper bound on how many transitions a single auto-resolve will chain
# through to reach the target status -- guards against looping forever if
# the workflow graph has a cycle the walk can't otherwise detect.
MAX_TRANSITION_HOPS = 5


class ActionType(str, Enum):
    CREATE = "create"
    LOG_WORK = "log_work"
    RESOLVE = "resolve"
    NONE = "none"


_ACTION_TYPE_BY_DECISION = {
    RoutingDecision.AUTO_CREATE: ActionType.CREATE,
    RoutingDecision.PROPOSE_CREATE: ActionType.CREATE,
    RoutingDecision.AUTO_LOG_WORK: ActionType.LOG_WORK,
    RoutingDecision.AUTO_RESOLVE: ActionType.RESOLVE,
    RoutingDecision.PROPOSE_RESOLVE: ActionType.RESOLVE,
    RoutingDecision.SKIP_AS_NOISE: ActionType.NONE,
}

AUTO_DECISIONS = {RoutingDecision.AUTO_CREATE, RoutingDecision.AUTO_LOG_WORK, RoutingDecision.AUTO_RESOLVE}


def action_type_for(decision: RoutingDecision) -> ActionType:
    return _ACTION_TYPE_BY_DECISION[decision]


def is_auto(decision: RoutingDecision) -> bool:
    return decision in AUTO_DECISIONS


class ActionStepResult(BaseModel):
    step: str  # "create" | "comment" | "worklog" | "transition"
    ok: bool
    error: str | None = None


class ActionResult(BaseModel):
    action_type: ActionType
    jira_issue_key: str | None
    steps: list[ActionStepResult]

    @property
    def all_ok(self) -> bool:
        return all(s.ok for s in self.steps)


async def execute_action(
    action_type: ActionType,
    classification: FeedClassification,
    jira: JiraClient,
    settings: Settings,
    issue_type: str | None = None,
    reporting_service_key: str | None = None,
    extra_field_values: dict[str, str] | None = None,
) -> ActionResult:
    """Perform the Jira side effects for a decided action.

    Independent of whether the decision was auto-executed or a
    human-confirmed proposal -- both paths converge here with the same
    action_type once the decision to act has been made. issue_type,
    reporting_service_key, and extra_field_values, when given, override/
    extend the CREATE payload -- they're the human's/UI's choices, not
    something the classifier decides.
    """
    if action_type is ActionType.CREATE:
        return await _create(
            classification,
            jira,
            settings,
            issue_type or settings.jira_issue_type,
            reporting_service_key,
            extra_field_values,
        )
    if action_type is ActionType.LOG_WORK:
        return await _log_work(classification, jira, settings)
    if action_type is ActionType.RESOLVE:
        return await _resolve(classification, jira, settings)
    return ActionResult(action_type=ActionType.NONE, jira_issue_key=None, steps=[])


def _build_create_extra_fields(
    settings: Settings, reporting_service_key: str | None, extra_field_values: dict[str, str] | None
) -> dict | None:
    extra_fields = dict(settings.jira_extra_create_fields)
    if reporting_service_key and settings.jira_reporting_service_field_id:
        extra_fields[settings.jira_reporting_service_field_id] = [{"key": reporting_service_key}]
    if extra_field_values:
        for field_id, option_id in extra_field_values.items():
            if field_id in settings.jira_extra_select_fields and option_id:
                extra_fields[field_id] = {"id": option_id}
    return extra_fields or None


async def _create(
    classification: FeedClassification,
    jira: JiraClient,
    settings: Settings,
    issue_type: str,
    reporting_service_key: str | None = None,
    extra_field_values: dict[str, str] | None = None,
) -> ActionResult:
    try:
        result = await jira.create_issue(
            project_key=settings.jira_project_key,
            issue_type=issue_type,
            summary=classification.title,
            description=classification.summary,
            labels=[settings.jira_managed_label],
            extra_fields=_build_create_extra_fields(settings, reporting_service_key, extra_field_values),
        )
        return ActionResult(
            action_type=ActionType.CREATE,
            jira_issue_key=result["key"],
            steps=[ActionStepResult(step="create", ok=True)],
        )
    except JiraClientError as exc:
        return ActionResult(
            action_type=ActionType.CREATE,
            jira_issue_key=None,
            steps=[ActionStepResult(step="create", ok=False, error=str(exc))],
        )


async def _log_work(classification: FeedClassification, jira: JiraClient, settings: Settings) -> ActionResult:
    key = classification.matched_ticket_key
    assert key is not None, "router guarantees a matched_ticket_key before AUTO_LOG_WORK"
    if not settings.jira_worklog_enabled:
        # Worklog permission isn't available -- fall back to a comment so the
        # update is still recorded on the ticket somewhere.
        try:
            await jira.add_comment(key, classification.summary)
            steps = [ActionStepResult(step="comment", ok=True)]
        except JiraClientError as exc:
            steps = [ActionStepResult(step="comment", ok=False, error=str(exc))]
        return ActionResult(action_type=ActionType.LOG_WORK, jira_issue_key=key, steps=steps)
    try:
        await jira.add_worklog(key, WORKLOG_TIME_SPENT, classification.summary)
        steps = [ActionStepResult(step="worklog", ok=True)]
    except JiraClientError as exc:
        steps = [ActionStepResult(step="worklog", ok=False, error=str(exc))]
    return ActionResult(action_type=ActionType.LOG_WORK, jira_issue_key=key, steps=steps)


async def _walk_to_target_status(
    jira: JiraClient,
    key: str,
    target_status_name: str,
    current_status_name: str | None,
    target_fields: dict[str, str] | None = None,
) -> str | None:
    """Chain transitions toward target_status_name, one hop at a time.

    Many real workflows can't reach the resolved status in a single
    transition (e.g. Open -> Assigned -> In Progress -> Resolved), so a
    direct find-and-transition isn't enough. At each hop this takes the
    target transition if it's directly available; otherwise it takes the
    single unambiguous "forward" transition -- excluding self-loops and any
    transition into a *different* terminal (Done-category) status, since
    those are alternate endings (e.g. Withdrawn, Rejected) that must never
    be guessed into. If more than one forward candidate remains, or none
    do, the walk stops rather than risk taking the wrong branch.

    target_fields, when given, are submitted on whichever transition actually
    lands on target_status_name (e.g. a "Solution" field some workflows
    require on their terminal Resolve transition) -- never on an
    intermediate hop, since those fields are specific to landing on that
    status.

    Returns None on success, or an error string describing why no safe path
    was found.
    """
    visited: set[str] = {current_status_name} if current_status_name else set()
    for _ in range(MAX_TRANSITION_HOPS):
        transitions = await jira.get_transitions(key)
        direct = next(
            (t for t in transitions if t["to"]["name"].lower() == target_status_name.lower()), None
        )
        if direct is not None:
            await jira.do_transition(key, direct["id"], fields=target_fields)
            return None

        by_target = {
            t["to"]["name"]: t
            for t in transitions
            if t["to"]["name"] not in visited and t["to"]["statusCategory"]["name"] != "Done"
        }
        if len(by_target) != 1:
            return f"No unambiguous path to '{target_status_name}' found"
        (transition,) = by_target.values()
        visited.add(transition["to"]["name"])
        await jira.do_transition(key, transition["id"])
    return f"No path to '{target_status_name}' found within {MAX_TRANSITION_HOPS} hops"


async def _resolve(classification: FeedClassification, jira: JiraClient, settings: Settings) -> ActionResult:
    # Agentic resolve (app/action_agent.py) needs a real Anthropic API key --
    # Tool Runner is Anthropic-API-only, with no equivalent for the on-prem
    # OpenAI-compatible endpoint classification uses. Without a key, fall
    # back to the deterministic path below so nothing already working breaks.
    # Imported lazily to avoid a circular import (action_agent imports the
    # ActionResult/ActionStepResult/ActionType types defined in this module).
    if settings.anthropic_api_key:
        from app.action_agent import run_resolve_agent

        return await run_resolve_agent(classification, jira, settings)
    return await _resolve_deterministic(classification, jira, settings)


async def _resolve_deterministic(
    classification: FeedClassification, jira: JiraClient, settings: Settings
) -> ActionResult:
    key = classification.matched_ticket_key
    assert key is not None, "router guarantees a matched_ticket_key before AUTO_RESOLVE/PROPOSE_RESOLVE"
    steps: list[ActionStepResult] = []

    # Each sub-step runs independently so a later failure (e.g. transition)
    # doesn't hide that earlier steps (comment, worklog) already succeeded.
    comment_body = classification.resolution_comment or classification.summary
    try:
        await jira.add_comment(key, comment_body)
        steps.append(ActionStepResult(step="comment", ok=True))
    except JiraClientError as exc:
        steps.append(ActionStepResult(step="comment", ok=False, error=str(exc)))

    # An issue can already be in a terminal status (e.g. manually withdrawn
    # before a scheduled resolve fires). Jira's own workflow permissions
    # block logging work against a closed issue, and there's no meaningful
    # "resolved" transition to make from a status that's already Done --
    # attempting both is a guaranteed, non-actionable failure, so skip them
    # rather than reporting noise the operator can't do anything about.
    try:
        issue = await jira.get_issue(key, fields=["status"])
        current_status_name = issue["fields"]["status"]["name"]
        already_closed = issue["fields"]["status"]["statusCategory"]["name"] == "Done"
    except JiraClientError:
        current_status_name = None
        already_closed = False

    if already_closed:
        steps.append(ActionStepResult(step="worklog", ok=True))
        steps.append(ActionStepResult(step="transition", ok=True))
        return ActionResult(action_type=ActionType.RESOLVE, jira_issue_key=key, steps=steps)

    if settings.jira_worklog_enabled:
        try:
            await jira.add_worklog(key, WORKLOG_TIME_SPENT, "AI-triaged resolution")
            steps.append(ActionStepResult(step="worklog", ok=True))
        except JiraClientError as exc:
            steps.append(ActionStepResult(step="worklog", ok=False, error=str(exc)))
    else:
        steps.append(ActionStepResult(step="worklog", ok=True))

    target_fields = None
    if settings.jira_resolution_field_id:
        target_fields = {settings.jira_resolution_field_id: comment_body}

    try:
        error = await _walk_to_target_status(
            jira, key, settings.jira_resolved_transition_name, current_status_name, target_fields
        )
        steps.append(ActionStepResult(step="transition", ok=error is None, error=error))
    except JiraClientError as exc:
        steps.append(ActionStepResult(step="transition", ok=False, error=str(exc)))

    return ActionResult(action_type=ActionType.RESOLVE, jira_issue_key=key, steps=steps)
