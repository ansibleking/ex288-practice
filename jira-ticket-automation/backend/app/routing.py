from __future__ import annotations

from enum import Enum

from app.classifier import FeedClassification, Intent, severity_rank
from app.config import Settings


class RoutingDecision(str, Enum):
    AUTO_CREATE = "auto_create"
    PROPOSE_CREATE = "propose_create"
    AUTO_LOG_WORK = "auto_log_work"
    AUTO_RESOLVE = "auto_resolve"
    PROPOSE_RESOLVE = "propose_resolve"
    SKIP_AS_NOISE = "skip_as_noise"


def _meets_auto_bar(classification: FeedClassification, settings: Settings) -> bool:
    return (
        classification.confidence >= settings.autonomy_auto_confidence_min
        and severity_rank(classification.severity) <= severity_rank(settings.autonomy_auto_severity_max)
    )


def route(classification: FeedClassification, settings: Settings) -> RoutingDecision:
    """Pure, deterministic mapping from an LLM classification to an action.

    The LLM never decides whether an action actually fires -- it only
    produces the classification (intent/confidence/severity/match). This
    function is the sole place autonomy thresholds are applied, so every
    decision is reproducible and unit-testable without touching Jira or
    the Anthropic API.
    """
    if classification.intent is Intent.NOISE:
        return RoutingDecision.SKIP_AS_NOISE

    if classification.intent in (Intent.NEW_ISSUE, Intent.SERVICE_REQUEST):
        return RoutingDecision.AUTO_CREATE if _meets_auto_bar(classification, settings) else RoutingDecision.PROPOSE_CREATE

    if classification.intent is Intent.UPDATE_EXISTING:
        if classification.matched_ticket_key is None:
            # Ambiguous "update" with no real match -- fall back to proposing
            # a new ticket rather than a distinct "ask which ticket" flow.
            return RoutingDecision.PROPOSE_CREATE
        if classification.confidence >= settings.autonomy_update_confidence_min:
            return RoutingDecision.AUTO_LOG_WORK
        return RoutingDecision.PROPOSE_CREATE

    if classification.intent is Intent.RESOLVED:
        if classification.matched_ticket_key is None:
            return RoutingDecision.SKIP_AS_NOISE
        return RoutingDecision.AUTO_RESOLVE if _meets_auto_bar(classification, settings) else RoutingDecision.PROPOSE_RESOLVE

    return RoutingDecision.SKIP_AS_NOISE  # unreachable, defensive default
