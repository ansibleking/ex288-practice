from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm import get_llm_client
from app.llm.base import StructuredLLMClient

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class Intent(str, Enum):
    NEW_ISSUE = "new_issue"
    SERVICE_REQUEST = "service_request"
    UPDATE_EXISTING = "update_existing"
    RESOLVED = "resolved"
    NOISE = "noise"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def severity_rank(severity: Severity | str) -> int:
    value = severity.value if isinstance(severity, Severity) else severity
    return SEVERITY_RANK[value]


class CandidateTicket(BaseModel):
    key: str
    summary: str
    description_excerpt: str


class FeedClassification(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    matched_ticket_key: str | None = Field(
        default=None,
        description=(
            "Jira key of an existing AI-managed ticket this feed text refers to, "
            "if intent is update_existing or resolved. Must be one of the "
            "candidate keys provided, or null."
        ),
    )
    title: str = Field(description="Short title, used as the Jira summary if a new ticket is created")
    summary: str = Field(description="1-3 sentence description of the situation")
    reasoning: str = Field(description="Brief explanation of why this intent/confidence/severity were chosen")
    resolution_comment: str | None = Field(
        default=None,
        description="Populated only when intent is 'resolved': a short resolution summary to post as a Jira comment.",
    )


_SYSTEM_PROMPT = """\
You triage free-text reports for a Jira-backed ChatOps/AIOps workflow. Reports \
fall into two broad kinds: operational problems (incidents) and actionable \
asks (requests for access, provisioning, or another change) -- both are \
ticket-worthy, not just incidents. For each report, decide:

- new_issue: describes an operational problem (an outage, error, degradation) \
  that is not already covered by any candidate ticket below and should \
  become a new Jira ticket.
- service_request: an actionable ask that is NOT reporting a problem -- e.g. \
  provisioning access, granting a permission, requesting a new account, \
  a configuration change, or another routine fulfillment request. This is \
  still ticket-worthy; do not classify a clear, actionable request as noise \
  just because nothing is broken.
- update_existing: provides new information about a situation already covered \
  by one of the candidate tickets, but does not indicate it is resolved.
- resolved: indicates a situation covered by one of the candidate tickets has \
  been fixed, mitigated, fulfilled, or is no longer occurring.
- noise: not an actionable operational signal (e.g. small talk, an unrelated \
  question, or too vague to act on either as a problem or as a request).

Rules:
- matched_ticket_key must be one of the candidate ticket keys given to you, or \
  null. Never invent a key. It must be null when intent is new_issue or \
  service_request.
- confidence is your calibrated confidence (0.0-1.0) in this classification, \
  not just in the severity assessment.
- severity reflects operational impact for new_issue/update_existing/resolved. \
  For service_request, treat it as the urgency of fulfillment (usually low or \
  medium, since nothing is broken) rather than incident impact.
- resolution_comment must be set (a short, factual resolution/fulfillment \
  summary) when intent is resolved, and left null otherwise.
- Be conservative: prefer noise or a lower confidence when the report is vague \
  rather than guessing.\
"""


def _format_candidates(candidates: list[CandidateTicket]) -> str:
    if not candidates:
        return "(no open AI-managed tickets currently tracked)"
    lines = [f'- {c.key}: "{c.summary}" — "{c.description_excerpt}"' for c in candidates]
    return "\n".join(lines)


async def classify(
    text: str,
    candidates: list[CandidateTicket],
    settings: Settings,
    llm_client: StructuredLLMClient | None = None,
) -> FeedClassification:
    owns_client = llm_client is None
    llm_client = llm_client or get_llm_client(settings)
    user_content = (
        f"## Candidate open AI-managed tickets\n{_format_candidates(candidates)}\n\n"
        f"## Incoming feed text\n{text}"
    )
    try:
        parsed = await llm_client.parse(
            system=_SYSTEM_PROMPT, user_content=user_content, output_model=FeedClassification
        )
    finally:
        if owns_client:
            aclose = getattr(llm_client, "aclose", None)
            if aclose is not None:
                await aclose()

    # Defensive re-validation: never trust the model's string match on its own.
    candidate_keys = {c.key for c in candidates}
    if parsed.intent in (Intent.NEW_ISSUE, Intent.SERVICE_REQUEST):
        parsed = parsed.model_copy(update={"matched_ticket_key": None})
    elif parsed.matched_ticket_key is not None and parsed.matched_ticket_key not in candidate_keys:
        parsed = parsed.model_copy(update={"matched_ticket_key": None})

    return parsed
