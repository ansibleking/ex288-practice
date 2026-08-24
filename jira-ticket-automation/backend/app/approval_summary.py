from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm import get_llm_client
from app.llm.base import StructuredLLMClient
from app.tickets import TicketApprovalDetail


class ApprovalSummary(BaseModel):
    overview: str = Field(description="1-3 sentence plain-language summary of what's being requested")
    key_details: list[str] = Field(
        description="Short bullet points of the concrete request details (what, for whom, why)"
    )
    concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Anything worth double-checking before approving -- missing info, unusual scope, "
            "cost/risk signals. Empty if nothing stands out."
        ),
    )
    recommendation: Literal["approve", "reject", "needs_more_info"]
    reasoning: str = Field(description="Brief explanation for the recommendation")


_SYSTEM_PROMPT = """\
You help a Jira approver quickly understand a pending approval-workflow ticket \
(e.g. an IT hardware, access, or change request) before they decide. You are \
advisory only -- you never approve or reject anything yourself; a human always \
makes and clicks the final decision in Jira. Given the ticket's content:

- overview: what is actually being asked for, in plain language.
- key_details: the concrete specifics (what resource/item, for which \
  project/environment, requested by whom, and the stated reason) as short \
  bullet points -- not a restatement of the overview.
- concerns: anything that would make a careful approver pause -- missing \
  justification, unusually large scope, production impact, a cost/risk \
  signal, etc. Leave empty if nothing stands out; don't invent concerns.
- recommendation: "approve" if it looks routine and well-justified, "reject" \
  if it looks invalid or clearly out of policy, or "needs_more_info" if the \
  ticket is missing what's needed to decide either way.
- reasoning: a brief, concrete explanation for the recommendation, referencing \
  the actual ticket content.

Be conservative: prefer needs_more_info over guessing when the ticket content \
is thin or ambiguous.\
"""


def _format_ticket(ticket: TicketApprovalDetail) -> str:
    lines = [
        f"Summary: {ticket.summary}",
        f"Issue type: {ticket.issue_type}",
        f"Status: {ticket.status}",
        f"Reporter: {ticket.reporter or 'unknown'}",
        f"Description: {ticket.description or '(none)'}",
        "",
        "Additional fields:",
    ]
    if ticket.fields:
        lines += [f"- {entry.label}: {entry.value}" for entry in ticket.fields]
    else:
        lines.append("(none)")
    return "\n".join(lines)


async def summarize_for_approval(
    ticket: TicketApprovalDetail,
    settings: Settings,
    llm_client: StructuredLLMClient | None = None,
) -> ApprovalSummary:
    owns_client = llm_client is None
    llm_client = llm_client or get_llm_client(settings)
    try:
        return await llm_client.parse(
            system=_SYSTEM_PROMPT, user_content=_format_ticket(ticket), output_model=ApprovalSummary
        )
    finally:
        if owns_client:
            aclose = getattr(llm_client, "aclose", None)
            if aclose is not None:
                await aclose()
