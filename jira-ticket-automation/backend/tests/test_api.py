from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditStore
from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings, get_settings
from app.jira_client import JiraClientError
from app.main import app
from app.schedule_store import ScheduleStore


def _settings(tmp_path) -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        jira_issue_type="Task",
        jira_managed_label="aiops-managed",
        jira_resolved_transition_name="Done",
        anthropic_api_key="sk-ant-test-key",
        database_path=str(tmp_path / "audit.db"),
    )


@pytest.fixture(autouse=True)
def _wire_app(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[get_settings] = lambda: settings
    get_settings.cache_clear()

    # Deliberately not entering TestClient as a context manager anywhere in
    # this file: that would trigger the app's lifespan, which constructs a
    # real JiraClient/AuditStore and overwrites the mocks set here.
    app.state.jira_client = AsyncMock()
    app.state.jira_client.search_issues.return_value = {"issues": []}
    app.state.audit_store = AuditStore(str(tmp_path / "audit.db"))
    app.state.schedule_store = ScheduleStore(str(tmp_path / "audit.db"))

    yield

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.95,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Seeing intermittent 503s",
        reasoning="clear signal",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


def _patch_classify(monkeypatch, classification: FeedClassification):
    async def fake_classify(text, candidates, settings, client=None):
        return classification

    monkeypatch.setattr("app.feed_service.classify", fake_classify)


def test_health_reports_jira_reachable():
    app.state.jira_client.whoami.return_value = {"displayName": "Service Account"}
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["jira_reachable"] is True
    assert body["llm_configured"] is True
    assert body["llm_provider"] == "anthropic"
    assert body["reporting_service_configured"] is False


def test_non_asset_responses_are_not_cached():
    app.state.jira_client.whoami.return_value = {"displayName": "Service Account"}
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_submit_feed_auto_creates_ticket(monkeypatch):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    app.state.jira_client.create_issue.return_value = {"key": "AIOPS-42"}

    client = TestClient(app)
    response = client.post("/api/feed", json={"text": "payments-svc 503s", "source": "chat"})

    assert response.status_code == 200
    body = response.json()
    assert body["action_status"] == "executed"
    assert body["jira_issue_key"] == "AIOPS-42"
    assert body["routing_decision"] == "auto_create"


def test_submit_feed_low_confidence_returns_pending_without_jira_write(monkeypatch):
    _patch_classify(monkeypatch, _classification(confidence=0.1, severity=Severity.LOW))

    client = TestClient(app)
    response = client.post("/api/feed", json={"text": "maybe something?", "source": "paste"})

    assert response.status_code == 200
    body = response.json()
    assert body["action_status"] == "pending_confirmation"
    assert body["jira_issue_key"] is None
    app.state.jira_client.create_issue.assert_not_awaited()


def test_submit_feed_file_extracts_text(monkeypatch):
    _patch_classify(monkeypatch, _classification(intent=Intent.NOISE))

    client = TestClient(app)
    response = client.post(
        "/api/feed/file", files={"file": ("notes.txt", b"just some notes", "text/plain")}
    )

    assert response.status_code == 200
    assert response.json()["action_status"] == "skipped"


def test_submit_feed_file_rejects_non_utf8():
    client = TestClient(app)
    response = client.post(
        "/api/feed/file", files={"file": ("bad.bin", b"\xff\xfe\x00\x01", "application/octet-stream")}
    )

    assert response.status_code == 400


def test_pending_confirm_and_cancel_flow(monkeypatch):
    _patch_classify(monkeypatch, _classification(confidence=0.1, severity=Severity.LOW))
    client = TestClient(app)

    submit = client.post("/api/feed", json={"text": "ambiguous report", "source": "chat"})
    audit_id = submit.json()["audit_id"]

    pending_list = client.get("/api/pending")
    assert any(row["id"] == audit_id for row in pending_list.json())

    app.state.jira_client.create_issue.return_value = {"key": "AIOPS-7"}
    confirm = client.post(f"/api/pending/{audit_id}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["action_status"] == "confirmed"
    assert confirm.json()["jira_issue_key"] == "AIOPS-7"

    # Already confirmed -- cancelling now should 409
    cancel_again = client.post(f"/api/pending/{audit_id}/cancel")
    assert cancel_again.status_code == 409


def test_pending_cancel_marks_cancelled(monkeypatch):
    _patch_classify(monkeypatch, _classification(confidence=0.1, severity=Severity.LOW))
    client = TestClient(app)

    submit = client.post("/api/feed", json={"text": "ambiguous report", "source": "chat"})
    audit_id = submit.json()["audit_id"]

    cancel = client.post(f"/api/pending/{audit_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["action_status"] == "cancelled"
    app.state.jira_client.create_issue.assert_not_awaited()


def test_pending_confirm_404_for_unknown_id():
    client = TestClient(app)
    response = client.post("/api/pending/999/confirm")
    assert response.status_code == 404


def test_pending_confirm_with_overrides(monkeypatch):
    _patch_classify(monkeypatch, _classification(confidence=0.1, severity=Severity.LOW, title="Original"))
    client = TestClient(app)

    submit = client.post("/api/feed", json={"text": "ambiguous report", "source": "chat"})
    audit_id = submit.json()["audit_id"]

    app.state.jira_client.create_issue.return_value = {"key": "AIOPS-8"}
    confirm = client.post(
        f"/api/pending/{audit_id}/confirm", json={"title": "Edited title", "severity": "high"}
    )

    assert confirm.status_code == 200
    body = confirm.json()
    assert body["classification"]["title"] == "Edited title"
    assert body["classification"]["severity"] == "high"
    create_kwargs = app.state.jira_client.create_issue.await_args.kwargs
    assert create_kwargs["summary"] == "Edited title"


def test_tickets_mine_returns_assigned_and_reported_tickets():
    app.state.jira_client.search_issues.return_value = {
        "issues": [
            {
                "key": "AIOPS-9",
                "fields": {
                    "summary": "Something to review",
                    "status": {"name": "Open"},
                    "priority": {"name": "Medium"},
                    "issuetype": {"name": "Task"},
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            }
        ]
    }
    client = TestClient(app)

    response = client.get("/api/tickets/mine")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["key"] == "AIOPS-9"
    assert body["items"][0]["status"] == "Open"


def test_tickets_mine_passes_through_date_filters_and_pagination():
    app.state.jira_client.search_issues.return_value = {"issues": [], "total": 0}
    client = TestClient(app)

    response = client.get(
        "/api/tickets/mine",
        params={"start_date": "2026-08-01", "end_date": "2026-08-19", "limit": 5, "offset": 10},
    )

    assert response.status_code == 200
    jql = app.state.jira_client.search_issues.await_args.args[0]
    call_kwargs = app.state.jira_client.search_issues.await_args.kwargs
    assert '"2026-08-01"' in jql
    assert '"2026-08-20"' in jql  # end_date made exclusive of the following day
    assert call_kwargs["start_at"] == 10
    assert call_kwargs["max_results"] == 5


def test_audit_list_and_get(monkeypatch):
    _patch_classify(monkeypatch, _classification(intent=Intent.NOISE))
    client = TestClient(app)

    submit = client.post("/api/feed", json={"text": "hi", "source": "chat"})
    audit_id = submit.json()["audit_id"]

    listed = client.get("/api/audit")
    assert listed.status_code == 200
    assert any(row["id"] == audit_id for row in listed.json())

    fetched = client.get(f"/api/audit/{audit_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == audit_id

    missing = client.get("/api/audit/999")
    assert missing.status_code == 404


def test_tickets_detail_returns_full_ticket():
    app.state.jira_client.get_issue.return_value = {
        "key": "AIOPS-3",
        "fields": {
            "summary": "Detail view test",
            "description": "Some description",
            "status": {"name": "Open"},
            "priority": {"name": "Low"},
            "issuetype": {"name": "Task"},
            "assignee": None,
            "reporter": {"displayName": "Carol"},
            "created": "2026-08-10T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
            "comment": {"comments": []},
        },
    }
    client = TestClient(app)

    response = client.get("/api/tickets/AIOPS-3")

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "AIOPS-3"
    assert body["reporter"] == "Carol"
    assert body["comments"] == []
    assert body["attachments"] == []


def test_tickets_upload_attachment_returns_refreshed_detail():
    app.state.jira_client.add_attachment.return_value = [{"id": "10001", "filename": "screenshot.png"}]
    app.state.jira_client.get_issue.return_value = {
        "key": "AIOPS-3",
        "fields": {
            "summary": "Detail view test",
            "description": "Some description",
            "status": {"name": "Open"},
            "priority": {"name": "Low"},
            "issuetype": {"name": "Task"},
            "assignee": None,
            "reporter": {"displayName": "Carol"},
            "created": "2026-08-10T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
            "comment": {"comments": []},
            "attachment": [
                {
                    "id": "10001",
                    "filename": "screenshot.png",
                    "size": 1024,
                    "mimeType": "image/png",
                    "author": {"displayName": "Carol"},
                    "created": "2026-08-19T10:00:00.000+0000",
                    "content": "https://jira.example.internal/secure/attachment/10001/screenshot.png",
                }
            ],
        },
    }
    client = TestClient(app)

    response = client.post(
        "/api/tickets/AIOPS-3/attachments",
        files={"file": ("screenshot.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "AIOPS-3"
    assert body["attachments"][0]["filename"] == "screenshot.png"
    app.state.jira_client.add_attachment.assert_awaited_once()
    add_kwargs = app.state.jira_client.add_attachment.await_args.kwargs
    assert add_kwargs["filename"] == "screenshot.png"
    assert add_kwargs["content"] == b"fake-image-bytes"


def test_tickets_issue_types_returns_list(monkeypatch):
    app.state.jira_client.get_create_issue_types.return_value = ["Service Request", "Task"]
    client = TestClient(app)

    response = client.get("/api/tickets/issue-types")

    assert response.status_code == 200
    assert response.json() == ["Service Request", "Task"]


def test_tickets_reporting_services_returns_empty_when_not_configured():
    client = TestClient(app)

    response = client.get("/api/tickets/reporting-services")

    assert response.status_code == 200
    assert response.json() == []
    app.state.jira_client.search_insight_objects.assert_not_called()


def test_tickets_reporting_services_returns_options_when_configured(tmp_path):
    settings = _settings(tmp_path).model_copy(update={"jira_reporting_service_field_id": "customfield_14503"})
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.jira_client.search_insight_objects.return_value = [
        {"id": 1, "objectKey": "SD-1179", "label": "Aabaar"},
    ]
    client = TestClient(app)

    response = client.get("/api/tickets/reporting-services", params={"q": "aab"})

    assert response.status_code == 200
    body = response.json()
    assert body == [{"key": "SD-1179", "label": "Aabaar"}]
    call_kwargs = app.state.jira_client.search_insight_objects.await_args.kwargs
    assert call_kwargs["query"] == "aab"


def test_tickets_extra_select_fields_returns_empty_when_not_configured():
    client = TestClient(app)

    response = client.get("/api/tickets/extra-select-fields")

    assert response.status_code == 200
    assert response.json() == []


def test_tickets_extra_select_fields_returns_options_when_configured(tmp_path):
    settings = _settings(tmp_path).model_copy(
        update={
            "jira_field_metadata_reference_issue": "SDIMD-80022",
            "jira_extra_select_fields": {"customfield_36200": "Subsidiary"},
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.jira_client.get_editmeta.return_value = {
        "customfield_36200": {
            "name": "Subsidiary",
            "allowedValues": [{"id": "43503", "value": "emaratech G", "disabled": False}],
        }
    }
    client = TestClient(app)

    response = client.get("/api/tickets/extra-select-fields")

    assert response.status_code == 200
    assert response.json() == [
        {
            "field_id": "customfield_36200",
            "label": "Subsidiary",
            "options": [{"id": "43503", "value": "emaratech G"}],
        }
    ]


def test_tickets_managed_returns_candidates():
    app.state.jira_client.search_issues.return_value = {
        "issues": [{"key": "AIOPS-1", "fields": {"summary": "s", "description": "d"}}]
    }
    client = TestClient(app)

    response = client.get("/api/tickets/managed")

    assert response.status_code == 200
    assert response.json()[0]["key"] == "AIOPS-1"


def test_approvals_list_only_includes_tickets_with_an_approval_transition():
    app.state.jira_client.search_issues.return_value = {
        "issues": [
            {
                "key": "SDIMD-74126",
                "fields": {
                    "summary": "Memory increase request",
                    "status": {"name": "Pending Line Manager"},
                    "issuetype": {"name": "IT Set Up - Hardware"},
                    "reporter": {"displayName": "Ilyas Ahmed"},
                    "updated": "2026-08-10T09:00:00.000+0000",
                },
            }
        ]
    }
    app.state.jira_client.get_transitions.return_value = [
        {"id": "21", "name": "Approve", "to": {"name": "IMD Domain Approval"}},
        {"id": "41", "name": "Reject", "to": {"name": "Open"}},
    ]
    client = TestClient(app)

    response = client.get("/api/approvals")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["key"] == "SDIMD-74126"
    assert [t["name"] for t in body[0]["transitions"]] == ["Approve", "Reject"]


def test_approvals_detail_filters_junk_fields_and_resolves_labels():
    app.state.jira_client.get_issue.return_value = {
        "key": "SDIMD-74126",
        "fields": {
            "summary": "Memory increase request",
            "description": "Please increase memory.",
            "status": {"name": "Pending Line Manager"},
            "issuetype": {"name": "IT Set Up - Hardware"},
            "assignee": {"displayName": "Mayilvahanan T"},
            "reporter": {"displayName": "Ilyas Ahmed"},
            "created": "2026-08-01T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
            "customfield_13657": {"value": "Production"},
            "customfield_36819": '<a href="https://jira/x">KB search</a>',
        },
    }
    app.state.jira_client.get_fields.return_value = [{"id": "customfield_13657", "name": "Environment"}]
    app.state.jira_client.get_transitions.return_value = [
        {"id": "21", "name": "Approve", "to": {"name": "IMD Domain Approval"}}
    ]
    client = TestClient(app)

    response = client.get("/api/approvals/SDIMD-74126")

    assert response.status_code == 200
    body = response.json()
    assert body["assignee"] == "Mayilvahanan T"
    labels = {f["label"]: f["value"] for f in body["fields"]}
    assert labels == {"Environment": "Production"}
    assert [t["name"] for t in body["transitions"]] == ["Approve"]


def test_approvals_summary_returns_llm_recommendation(monkeypatch):
    from app.approval_summary import ApprovalSummary

    async def fake_summarize(ticket, settings):
        return ApprovalSummary(
            overview="Memory increase for a production VM.",
            key_details=["bhmanwsus01, Biohub, Production"],
            concerns=[],
            recommendation="approve",
            reasoning="Routine capacity request.",
        )

    monkeypatch.setattr("app.routers.approvals.summarize_for_approval", fake_summarize)
    app.state.jira_client.get_issue.return_value = {
        "key": "SDIMD-74126",
        "fields": {
            "summary": "Memory increase request",
            "description": "Please increase memory.",
            "status": {"name": "Pending Line Manager"},
            "issuetype": {"name": "IT Set Up - Hardware"},
            "assignee": None,
            "reporter": None,
            "created": "2026-08-01T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
        },
    }
    app.state.jira_client.get_fields.return_value = []
    app.state.jira_client.get_transitions.return_value = []
    client = TestClient(app)

    response = client.get("/api/approvals/SDIMD-74126/summary")

    assert response.status_code == 200
    assert response.json()["recommendation"] == "approve"


def test_approvals_transition_executes_and_returns_refreshed_detail():
    app.state.jira_client.get_issue.return_value = {
        "key": "SDIMD-74126",
        "fields": {
            "summary": "Memory increase request",
            "description": "Please increase memory.",
            "status": {"name": "IMD Domain Approval"},
            "issuetype": {"name": "IT Set Up - Hardware"},
            "assignee": None,
            "reporter": None,
            "created": "2026-08-01T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
        },
    }
    app.state.jira_client.get_fields.return_value = []
    app.state.jira_client.get_transitions.return_value = []
    client = TestClient(app)

    response = client.post("/api/approvals/SDIMD-74126/transition", json={"transition_id": "21"})

    assert response.status_code == 200
    assert response.json()["status"] == "IMD Domain Approval"
    app.state.jira_client.do_transition.assert_awaited_once_with(
        "SDIMD-74126", "21", comment=None, fields=None
    )


def test_approvals_transition_passes_through_comment():
    app.state.jira_client.get_issue.return_value = {
        "key": "SDSEC-20602",
        "fields": {
            "summary": "Access request",
            "description": "",
            "status": {"name": "Pending Clarification"},
            "issuetype": {"name": "Network Access"},
            "assignee": None,
            "reporter": None,
            "created": "2026-08-01T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
        },
    }
    app.state.jira_client.get_fields.return_value = []
    app.state.jira_client.get_transitions.return_value = []
    client = TestClient(app)

    response = client.post(
        "/api/approvals/SDSEC-20602/transition",
        json={"transition_id": "421", "comment": "Please clarify the target environment."},
    )

    assert response.status_code == 200
    app.state.jira_client.do_transition.assert_awaited_once_with(
        "SDSEC-20602", "421", comment="Please clarify the target environment.", fields=None
    )


def test_approvals_transition_passes_through_extra_field_values():
    app.state.jira_client.get_issue.return_value = {
        "key": "SDSEC-20615",
        "fields": {
            "summary": "Software request",
            "description": "",
            "status": {"name": "Pending Security Review"},
            "issuetype": {"name": "IT Set Up - Software"},
            "assignee": None,
            "reporter": None,
            "created": "2026-08-01T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
        },
    }
    app.state.jira_client.get_fields.return_value = []
    app.state.jira_client.get_transitions.return_value = []
    client = TestClient(app)

    response = client.post(
        "/api/approvals/SDSEC-20615/transition",
        json={"transition_id": "91", "extra_field_values": {"customfield_32700": 4}},
    )

    assert response.status_code == 200
    app.state.jira_client.do_transition.assert_awaited_once_with(
        "SDSEC-20615", "91", comment=None, fields={"customfield_32700": 4}
    )


def test_approvals_transition_translates_missing_comment_error():
    app.state.jira_client.do_transition.side_effect = JiraClientError(
        'Jira API POST /issue/SDSEC-20643/transitions failed: 400 '
        '{"errorMessages":["Comment is required."],"errors":{}}'
    )
    client = TestClient(app)

    response = client.post(
        "/api/approvals/SDSEC-20643/transition",
        json={"transition_id": "421"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "This action requires a comment. Add one above and try again."


def test_approvals_transition_keeps_raw_error_for_other_failures():
    app.state.jira_client.do_transition.side_effect = JiraClientError(
        "Jira API POST /issue/SDSEC-20643/transitions failed: 400 "
        '{"errorMessages":[],"errors":{"customfield_14100":"Rejection Reason is required."}}'
    )
    client = TestClient(app)

    response = client.post(
        "/api/approvals/SDSEC-20643/transition",
        json={"transition_id": "241", "comment": "already provided"},
    )

    assert response.status_code == 502
    assert "Rejection Reason is required" in response.json()["detail"]


def test_sheets_parse_returns_parsed_workbook():
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Host", "IP"])
    workbook.active.append(["web01", "10.0.0.1"])
    buf = io.BytesIO()
    workbook.save(buf)
    client = TestClient(app)

    response = client.post(
        "/api/sheets/parse",
        files={
            "file": (
                "network-access.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "network-access.xlsx"
    assert body["sheets"][0]["headers"] == ["Host", "IP"]
    assert body["sheets"][0]["rows"] == [["web01", "10.0.0.1"]]


def test_sheets_diagram_returns_generated_graph(monkeypatch):
    import app.routers.sheets as sheets_router
    from app.network_diagram import DiagramEdge, DiagramNode, NetworkDiagram

    result = NetworkDiagram(
        nodes=[
            DiagramNode(id="web01", label="web01 (10.0.0.1)", role="source", zone="internal"),
            DiagramNode(id="db01", label="db01 (10.0.0.5)", role="destination", zone="internal"),
        ],
        edges=[
            DiagramEdge(source_id="web01", target_id="db01", label="TCP/5432", status="approved", reason=None)
        ],
        summary="web01 is granted database access to db01 over 5432.",
    )
    mock_generate = AsyncMock(return_value=result)
    monkeypatch.setattr(sheets_router, "generate_network_diagram", mock_generate)
    client = TestClient(app)

    response = client.post(
        "/api/sheets/diagram",
        json={"headers": ["Source", "Destination", "Port"], "rows": [["web01", "db01", "5432"]]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "web01 is granted database access to db01 over 5432."
    assert body["nodes"][0]["id"] == "web01"
    mock_generate.assert_awaited_once()


def test_sheets_diagram_translates_llm_errors(monkeypatch):
    import app.routers.sheets as sheets_router
    from app.llm.onprem_client import OnPremLLMError

    monkeypatch.setattr(
        sheets_router,
        "generate_network_diagram",
        AsyncMock(side_effect=OnPremLLMError("On-prem LLM endpoint unreachable")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/sheets/diagram",
        json={"headers": ["Source"], "rows": [["web01"]]},
    )

    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"]


def test_sheets_parse_rejects_unsupported_file_type():
    client = TestClient(app)

    response = client.post(
        "/api/sheets/parse",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert "Only .xlsx and .csv" in response.json()["detail"]


def test_get_llm_settings_treats_env_example_placeholder_as_not_configured(tmp_path):
    from app.config import get_settings as get_settings_dep

    settings = Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        anthropic_api_key="replace-with-anthropic-api-key",
        database_path=str(tmp_path / "audit.db"),
    )
    app.dependency_overrides[get_settings_dep] = lambda: settings
    client = TestClient(app)

    response = client.get("/api/settings/llm")

    assert response.json()["anthropic"]["configured"] is False


def test_get_llm_settings_reports_effective_provider_and_configured_status():
    # _settings() fixture: default_llm_provider defaults to "anthropic",
    # anthropic_api_key is set, onprem_llm_base_url is not.
    client = TestClient(app)

    response = client.get("/api/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["default_provider"] == "anthropic"
    assert body["override_active"] is False
    assert body["anthropic"]["configured"] is True
    assert body["onprem"]["configured"] is False


def test_put_llm_settings_sets_override_and_takes_effect_immediately():
    client = TestClient(app)

    response = client.put("/api/settings/llm", json={"provider": "onprem"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "onprem"
    assert body["override_active"] is True
    # A second GET reflects the same override -- proves it's persisted, not
    # just echoed back from the PUT response.
    follow_up = client.get("/api/settings/llm")
    assert follow_up.json()["provider"] == "onprem"


def test_put_llm_settings_null_clears_override():
    client = TestClient(app)
    client.put("/api/settings/llm", json={"provider": "onprem"})

    response = client.put("/api/settings/llm", json={"provider": None})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["override_active"] is False


def test_put_llm_settings_rejects_unknown_provider():
    client = TestClient(app)

    response = client.put("/api/settings/llm", json={"provider": "bogus"})

    assert response.status_code == 400


def test_test_llm_provider_reports_success(monkeypatch):
    import app.routers.settings as settings_router

    mock_client = AsyncMock()
    mock_client.parse.return_value = settings_router._PingResult(ok=True)
    monkeypatch.setattr(settings_router, "get_llm_client_for_provider", lambda *a, **k: mock_client)
    client = TestClient(app)

    response = client.post("/api/settings/llm/test", json={"provider": "anthropic"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert isinstance(body["latency_ms"], int)
    mock_client.aclose.assert_awaited_once()


def test_test_llm_provider_reports_failure_without_crashing(monkeypatch):
    import app.routers.settings as settings_router

    mock_client = AsyncMock()
    mock_client.parse.side_effect = RuntimeError("Name or service not known")
    monkeypatch.setattr(settings_router, "get_llm_client_for_provider", lambda *a, **k: mock_client)
    client = TestClient(app)

    response = client.post("/api/settings/llm/test", json={"provider": "onprem"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "Name or service not known" in body["error"]
    mock_client.aclose.assert_awaited_once()


def test_schedule_create_and_list():
    client = TestClient(app)

    created = client.post(
        "/api/schedule",
        json={
            "start_at": "2026-08-17T09:00:00Z",
            "end_at": "2026-08-17T11:00:00Z",
            "text": "DB maintenance window",
            "issue_type": "Task",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "pending"
    assert body["text"] == "DB maintenance window"

    listed = client.get(
        "/api/schedule", params={"start": "2026-08-17T00:00:00+00:00", "end": "2026-08-18T00:00:00+00:00"}
    )
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json())


def test_schedule_create_persists_reporting_service_key():
    client = TestClient(app)

    created = client.post(
        "/api/schedule",
        json={
            "start_at": "2026-08-17T09:00:00Z",
            "text": "DB maintenance window",
            "issue_type": "Task",
            "reporting_service_key": "SD-1179",
        },
    )

    assert created.status_code == 200
    assert created.json()["reporting_service_key"] == "SD-1179"


def test_schedule_create_rejects_naive_datetime():
    client = TestClient(app)

    response = client.post(
        "/api/schedule",
        json={"start_at": "2026-08-17T09:00:00", "text": "no timezone", "issue_type": "Task"},
    )

    assert response.status_code == 422


def test_schedule_create_rejects_end_before_start():
    client = TestClient(app)

    response = client.post(
        "/api/schedule",
        json={
            "start_at": "2026-08-17T11:00:00Z",
            "end_at": "2026-08-17T09:00:00Z",
            "text": "backwards window",
            "issue_type": "Task",
        },
    )

    assert response.status_code == 422


def test_schedule_cancel_pending_item():
    client = TestClient(app)
    created = client.post(
        "/api/schedule",
        json={"start_at": "2026-08-17T09:00:00Z", "text": "x", "issue_type": "Task"},
    )
    item_id = created.json()["id"]

    cancelled = client.post(f"/api/schedule/{item_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_schedule_cancel_404_for_unknown_id():
    client = TestClient(app)
    response = client.post("/api/schedule/999/cancel")
    assert response.status_code == 404


def test_schedule_cancel_409_when_not_pending():
    client = TestClient(app)
    created = client.post(
        "/api/schedule",
        json={"start_at": "2026-08-17T09:00:00Z", "text": "x", "issue_type": "Task"},
    )
    item_id = created.json()["id"]
    client.post(f"/api/schedule/{item_id}/cancel")

    second_cancel = client.post(f"/api/schedule/{item_id}/cancel")

    assert second_cancel.status_code == 409
