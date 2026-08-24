import pytest

from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings
from app.routing import RoutingDecision, route

# Defaults under test: confidence_min=0.85, severity_max=medium, update_confidence_min=0.7
DEFAULT_SETTINGS = Settings(
    jira_base_url="https://jira.example.internal",
    jira_pat="test-token",
    jira_project_key="AIOPS",
    anthropic_api_key="test-anthropic-key",
)


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="t",
        summary="s",
        reasoning="r",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


def test_noise_always_skips_regardless_of_confidence_or_severity():
    c = _classification(intent=Intent.NOISE, confidence=1.0, severity=Severity.CRITICAL)
    assert route(c, DEFAULT_SETTINGS) is RoutingDecision.SKIP_AS_NOISE


class TestNewIssueConfidenceBoundary:
    def test_at_threshold_auto_creates(self):
        c = _classification(confidence=0.85, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_CREATE

    def test_just_below_threshold_proposes(self):
        c = _classification(confidence=0.849999, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_well_above_threshold_auto_creates(self):
        c = _classification(confidence=0.99, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_CREATE

    def test_well_below_threshold_proposes(self):
        c = _classification(confidence=0.1, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE


class TestNewIssueSeverityBoundary:
    def test_severity_at_max_auto_creates(self):
        c = _classification(confidence=0.95, severity=Severity.MEDIUM)  # max is medium
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_CREATE

    def test_severity_just_above_max_proposes_even_with_high_confidence(self):
        c = _classification(confidence=0.99, severity=Severity.HIGH)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_critical_severity_always_proposes_even_at_max_confidence(self):
        c = _classification(confidence=1.0, severity=Severity.CRITICAL)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_low_severity_auto_creates(self):
        c = _classification(confidence=0.9, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_CREATE


class TestServiceRequest:
    def test_at_confidence_threshold_auto_creates(self):
        c = _classification(intent=Intent.SERVICE_REQUEST, confidence=0.85, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_CREATE

    def test_just_below_confidence_threshold_proposes(self):
        c = _classification(intent=Intent.SERVICE_REQUEST, confidence=0.849999, severity=Severity.LOW)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_high_severity_proposes_even_at_full_confidence(self):
        c = _classification(intent=Intent.SERVICE_REQUEST, confidence=1.0, severity=Severity.HIGH)
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE


class TestUpdateExisting:
    def test_no_matched_ticket_falls_back_to_propose_create(self):
        c = _classification(
            intent=Intent.UPDATE_EXISTING, confidence=0.99, severity=Severity.LOW, matched_ticket_key=None
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_matched_ticket_at_confidence_threshold_auto_logs_work(self):
        c = _classification(
            intent=Intent.UPDATE_EXISTING, confidence=0.7, severity=Severity.LOW, matched_ticket_key="AIOPS-1"
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_LOG_WORK

    def test_matched_ticket_just_below_confidence_threshold_proposes(self):
        c = _classification(
            intent=Intent.UPDATE_EXISTING,
            confidence=0.699999,
            severity=Severity.LOW,
            matched_ticket_key="AIOPS-1",
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_CREATE

    def test_matched_ticket_high_severity_still_auto_logs_work(self):
        # Updates aren't gated on severity, only on the (lower) update confidence bar --
        # they're non-destructive (comment + worklog), unlike create/resolve.
        c = _classification(
            intent=Intent.UPDATE_EXISTING,
            confidence=0.9,
            severity=Severity.CRITICAL,
            matched_ticket_key="AIOPS-1",
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_LOG_WORK


class TestResolved:
    def test_no_matched_ticket_skips_as_noise(self):
        c = _classification(
            intent=Intent.RESOLVED, confidence=0.99, severity=Severity.LOW, matched_ticket_key=None
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.SKIP_AS_NOISE

    def test_matched_ticket_meets_auto_bar_auto_resolves(self):
        c = _classification(
            intent=Intent.RESOLVED, confidence=0.85, severity=Severity.MEDIUM, matched_ticket_key="AIOPS-1"
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.AUTO_RESOLVE

    def test_matched_ticket_just_below_confidence_proposes_resolve(self):
        c = _classification(
            intent=Intent.RESOLVED,
            confidence=0.849999,
            severity=Severity.MEDIUM,
            matched_ticket_key="AIOPS-1",
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_RESOLVE

    def test_matched_ticket_high_severity_proposes_resolve_even_at_full_confidence(self):
        c = _classification(
            intent=Intent.RESOLVED, confidence=1.0, severity=Severity.HIGH, matched_ticket_key="AIOPS-1"
        )
        assert route(c, DEFAULT_SETTINGS) is RoutingDecision.PROPOSE_RESOLVE


def test_thresholds_are_read_from_settings_not_hardcoded():
    lenient_settings = DEFAULT_SETTINGS.model_copy(
        update={"autonomy_auto_confidence_min": 0.1, "autonomy_auto_severity_max": "critical"}
    )
    c = _classification(confidence=0.2, severity=Severity.CRITICAL)
    assert route(c, lenient_settings) is RoutingDecision.AUTO_CREATE
