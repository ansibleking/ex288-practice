from __future__ import annotations

import json
from typing import Callable

from anthropic import AsyncAnthropic, beta_async_tool

from app.actions import ActionResult, ActionStepResult, ActionType
from app.classifier import FeedClassification
from app.config import Settings
from app.jira_client import JiraClient, JiraClientError
from app.tickets import _transition_extra_fields

# Tells the agent HOW to resolve a ticket that code has already decided
# should be resolved -- it never decides whether to act, only how. The
# never-guess-into-a-wrong-branch rule mirrors the deterministic walker this
# replaces (app/actions.py::_walk_to_target_status), restated as an
# instruction rather than an unbypassable code path -- a real change in
# guarantee strength, mitigated by every transition still landing in the
# audit trail the same way it always has.
_SYSTEM_PROMPT = """\
You resolve a Jira ticket that a triage system has already decided should be \
marked resolved -- your job is HOW to do it correctly on this specific \
ticket's real workflow, not whether to do it.

Steps:
1. Check the ticket's current status. If it's already in a Done-category \
   status, post the resolution comment and stop -- do not attempt a worklog \
   or transition.
2. Look at the available transitions. Find the one whose target status \
   matches "{target_status}". If it's not directly available, take the ONE \
   transition that is clearly a forward step toward it (not a self-loop, not \
   a different terminal status like Withdrawn/Rejected/Closed) and check \
   transitions again from the new status. Never guess between two or more \
   plausible forward transitions -- if it's ambiguous, stop and report why \
   instead of picking one.
3. Some transitions require extra fields on their screen (shown in \
   get_available_transitions). Fill required text/number fields using the \
   resolution comment text where that's a sensible value (e.g. a field \
   literally named "Solution" or "Resolution"); leave fields you can't \
   sensibly infer unset and let the transition attempt surface the real Jira \
   error rather than guessing a value.
4. Always post the resolution comment, exactly once.
5. Log work only if the add_worklog tool is available to you -- if it isn't, \
   worklog isn't possible on this project; don't try to substitute anything \
   else for it.

Never transition the ticket into a terminal status other than \
"{target_status}" -- Withdrawn, Rejected, Closed, or any other Done-category \
status are alternate endings, not equivalent to resolved, even if one is the \
only transition available. If you cannot safely reach "{target_status}", \
stop and explain why rather than settling for a different terminal status.\
"""


# Plain async implementations, separated from their @beta_async_tool wrappers
# below so tests can call them directly without depending on how the SDK's
# tool decorator wraps a function (undocumented/subject to change) -- the
# decorated closures in _build_tools are a thin binding layer only.


async def _get_ticket_status_impl(jira: JiraClient, key: str) -> str:
    issue = await jira.get_issue(key, fields=["status"])
    status = issue["fields"]["status"]
    return json.dumps({"name": status["name"], "category": status["statusCategory"]["name"]})


async def _get_available_transitions_impl(jira: JiraClient, key: str) -> str:
    transitions = await jira.get_transitions(key)
    result = []
    for t in transitions:
        extra_fields = _transition_extra_fields(t.get("fields") or {})
        result.append(
            {
                "id": t["id"],
                "name": t["name"],
                "to_status": t["to"]["name"],
                "to_status_category": t["to"]["statusCategory"]["name"],
                "extra_fields": [
                    {"field_id": f.field_id, "label": f.label, "type": f.type}
                    for f in extra_fields
                ],
            }
        )
    return json.dumps(result)


async def _add_comment_impl(
    jira: JiraClient, steps: list[ActionStepResult], key: str, body: str
) -> str:
    try:
        await jira.add_comment(key, body)
        steps.append(ActionStepResult(step="comment", ok=True))
        return "Comment posted."
    except JiraClientError as exc:
        steps.append(ActionStepResult(step="comment", ok=False, error=str(exc)))
        return f"Failed to post comment: {exc}"


async def _transition_ticket_impl(
    jira: JiraClient,
    steps: list[ActionStepResult],
    key: str,
    transition_id: str,
    fields_json: str = "{}",
    comment: str | None = None,
) -> str:
    try:
        fields = json.loads(fields_json) if fields_json and fields_json != "{}" else None
    except (json.JSONDecodeError, TypeError) as exc:
        return f"fields_json was not valid JSON: {exc}"
    try:
        await jira.do_transition(key, transition_id, comment=comment, fields=fields)
        steps.append(ActionStepResult(step="transition", ok=True))
        return "Transition executed."
    except JiraClientError as exc:
        steps.append(ActionStepResult(step="transition", ok=False, error=str(exc)))
        return f"Failed to transition: {exc}"


async def _add_worklog_impl(
    jira: JiraClient, steps: list[ActionStepResult], key: str, time_spent: str, comment: str
) -> str:
    try:
        await jira.add_worklog(key, time_spent, comment)
        steps.append(ActionStepResult(step="worklog", ok=True))
        return "Worklog added."
    except JiraClientError as exc:
        steps.append(ActionStepResult(step="worklog", ok=False, error=str(exc)))
        return f"Failed to add worklog: {exc}"


def _build_tools(
    jira: JiraClient, settings: Settings, steps: list[ActionStepResult]
) -> list[Callable]:
    @beta_async_tool
    async def get_ticket_status(key: str) -> str:
        """Get a Jira ticket's current status name and status category (e.g. To Do, In Progress, Done).

        Args:
            key: The Jira issue key, e.g. AIOPS-123.
        """
        return await _get_ticket_status_impl(jira, key)

    @beta_async_tool
    async def get_available_transitions(key: str) -> str:
        """List the transitions currently available on a ticket, including any extra fields each transition's screen requires beyond the built-in comment.

        Args:
            key: The Jira issue key, e.g. AIOPS-123.
        """
        return await _get_available_transitions_impl(jira, key)

    @beta_async_tool
    async def add_comment(key: str, body: str) -> str:
        """Post a comment on the ticket.

        Args:
            key: The Jira issue key, e.g. AIOPS-123.
            body: The comment text.
        """
        return await _add_comment_impl(jira, steps, key, body)

    @beta_async_tool
    async def transition_ticket(
        key: str, transition_id: str, fields_json: str = "{}", comment: str | None = None
    ) -> str:
        """Execute a transition on the ticket, optionally with extra field values and/or a comment attached to this specific transition.

        Args:
            key: The Jira issue key, e.g. AIOPS-123.
            transition_id: The transition id from get_available_transitions.
            fields_json: JSON object of extra field values this transition's screen requires, e.g. {"customfield_14608": "Confirmed fixed after deploy"}. Pass "{}" if none are required.
            comment: Optional comment to attach to this specific transition (separate from the main resolution comment).
        """
        return await _transition_ticket_impl(jira, steps, key, transition_id, fields_json, comment)

    tools: list[Callable] = [
        get_ticket_status,
        get_available_transitions,
        add_comment,
        transition_ticket,
    ]

    if settings.jira_worklog_enabled:
        # Only added to the tool list when actually usable -- omitting the
        # tool is a harder guarantee than describing the restriction in
        # prose and hoping the model doesn't reach for it anyway.
        @beta_async_tool
        async def add_worklog(key: str, time_spent: str, comment: str) -> str:
            """Log work time against the ticket.

            Args:
                key: The Jira issue key, e.g. AIOPS-123.
                time_spent: Jira time-spent format, e.g. "5m", "1h".
                comment: Worklog comment describing the work.
            """
            return await _add_worklog_impl(jira, steps, key, time_spent, comment)

        tools.append(add_worklog)

    return tools


def _build_prompt(classification: FeedClassification, key: str) -> str:
    comment = classification.resolution_comment or classification.summary
    return (
        f"Resolve ticket {key}.\n\n"
        f"Situation: {classification.summary}\n\n"
        f"Resolution comment to post: {comment}"
    )


async def run_resolve_agent(
    classification: FeedClassification, jira: JiraClient, settings: Settings
) -> ActionResult:
    key = classification.matched_ticket_key
    assert key is not None, "router guarantees a matched_ticket_key before AUTO_RESOLVE/PROPOSE_RESOLVE"

    steps: list[ActionStepResult] = []
    tools = _build_tools(jira, settings, steps)
    system = _SYSTEM_PROMPT.format(target_status=settings.jira_resolved_transition_name)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        runner = client.beta.messages.tool_runner(
            model=settings.agent_model,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=[{"role": "user", "content": _build_prompt(classification, key)}],
        )
        async for _ in runner:
            pass
    finally:
        await client.close()

    return ActionResult(action_type=ActionType.RESOLVE, jira_issue_key=key, steps=steps)
