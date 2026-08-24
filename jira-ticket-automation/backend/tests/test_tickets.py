from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.tickets import (
    FALLBACK_ISSUE_TYPES,
    _flatten_field_value,
    _is_substantive,
    _transition_extra_fields,
    approvals_jql,
    fetch_approval_detail,
    fetch_approval_tickets,
    fetch_candidate_tickets,
    fetch_extra_select_fields,
    fetch_issue_types,
    fetch_my_tickets,
    fetch_reporting_services,
    fetch_ticket_detail,
    managed_tickets_jql,
    my_tickets_jql,
)


def _settings(**overrides) -> Settings:
    defaults = dict(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        anthropic_api_key="test-anthropic-key",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_managed_tickets_jql_scopes_to_label_and_open_status():
    jql = managed_tickets_jql(_settings(jira_managed_label="aiops-managed"))
    assert 'labels = "aiops-managed"' in jql
    assert "statusCategory != Done" in jql


@pytest.mark.asyncio
async def test_fetch_candidate_tickets_maps_fields():
    jira = AsyncMock()
    jira.search_issues.return_value = {
        "issues": [
            {
                "key": "AIOPS-1",
                "fields": {
                    "summary": "DB pool exhaustion",
                    "description": "Seeing intermittent 503s on payments-svc since 10:14 UTC.",
                },
            },
            {
                "key": "AIOPS-2",
                "fields": {"summary": "No description ticket", "description": None},
            },
        ]
    }

    candidates = await fetch_candidate_tickets(jira, _settings())

    assert len(candidates) == 2
    assert candidates[0].key == "AIOPS-1"
    assert candidates[0].summary == "DB pool exhaustion"
    assert candidates[0].description_excerpt.startswith("Seeing intermittent 503s")
    assert candidates[1].description_excerpt == ""


@pytest.mark.asyncio
async def test_fetch_candidate_tickets_truncates_long_descriptions():
    jira = AsyncMock()
    long_description = "x" * 1000
    jira.search_issues.return_value = {
        "issues": [{"key": "AIOPS-1", "fields": {"summary": "s", "description": long_description}}]
    }

    candidates = await fetch_candidate_tickets(jira, _settings())

    assert len(candidates[0].description_excerpt) == 300


@pytest.mark.asyncio
async def test_fetch_candidate_tickets_empty_result():
    jira = AsyncMock()
    jira.search_issues.return_value = {"issues": []}

    candidates = await fetch_candidate_tickets(jira, _settings())

    assert candidates == []


def test_my_tickets_jql_scopes_to_current_user():
    jql = my_tickets_jql()
    assert "assignee = currentUser()" in jql
    assert "reporter = currentUser()" in jql


def test_my_tickets_jql_adds_start_date_clause():
    jql = my_tickets_jql(start_date="2026-08-01")
    assert 'updated >= "2026-08-01"' in jql


def test_my_tickets_jql_makes_end_date_exclusive_of_next_day():
    jql = my_tickets_jql(end_date="2026-08-19")
    assert 'updated < "2026-08-20"' in jql


def test_my_tickets_jql_omits_date_clauses_when_not_given():
    jql = my_tickets_jql()
    assert "updated >=" not in jql
    assert "updated <" not in jql


@pytest.mark.asyncio
async def test_fetch_my_tickets_maps_fields_and_builds_browse_url():
    jira = AsyncMock()
    jira.search_issues.return_value = {
        "issues": [
            {
                "key": "AIOPS-7",
                "fields": {
                    "summary": "Follow up on outage",
                    "status": {"name": "In Progress"},
                    "priority": {"name": "High"},
                    "issuetype": {"name": "Task"},
                    "assignee": {"displayName": "Alice"},
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            }
        ]
    }

    result = await fetch_my_tickets(jira, _settings(jira_base_url="https://jira.example.internal/"))

    assert len(result.items) == 1
    t = result.items[0]
    assert t.key == "AIOPS-7"
    assert t.status == "In Progress"
    assert t.priority == "High"
    assert t.issue_type == "Task"
    assert t.assignee == "Alice"
    assert t.url == "https://jira.example.internal/browse/AIOPS-7"


@pytest.mark.asyncio
async def test_fetch_my_tickets_handles_missing_priority():
    jira = AsyncMock()
    jira.search_issues.return_value = {
        "issues": [
            {
                "key": "AIOPS-8",
                "fields": {
                    "summary": "No priority set",
                    "status": {"name": "Open"},
                    "priority": None,
                    "issuetype": {"name": "Bug"},
                    "assignee": None,
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            }
        ]
    }

    result = await fetch_my_tickets(jira, _settings())

    assert result.items[0].priority is None
    assert result.items[0].assignee is None


@pytest.mark.asyncio
async def test_fetch_my_tickets_passes_pagination_through_and_reports_total():
    jira = AsyncMock()
    jira.search_issues.return_value = {"issues": [], "total": 137}

    result = await fetch_my_tickets(jira, _settings(), limit=5, offset=10)

    jira.search_issues.assert_awaited_once()
    call_kwargs = jira.search_issues.await_args.kwargs
    assert call_kwargs["start_at"] == 10
    assert call_kwargs["max_results"] == 5
    assert result.total == 137
    assert result.items == []


@pytest.mark.asyncio
async def test_fetch_ticket_detail_maps_fields_and_comments():
    jira = AsyncMock()
    jira.get_issue.return_value = {
        "key": "AIOPS-1",
        "fields": {
            "summary": "DB pool exhaustion",
            "description": "Full description here",
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Service Request"},
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "created": "2026-08-10T09:00:00.000+0000",
            "updated": "2026-08-15T10:00:00.000+0000",
            "comment": {
                "comments": [
                    {"author": {"displayName": "Alice"}, "body": "Looking into it", "created": "2026-08-11T00:00:00.000+0000"}
                ]
            },
        },
    }

    detail = await fetch_ticket_detail(jira, _settings(jira_base_url="https://jira.example.internal"), "AIOPS-1")

    jira.get_issue.assert_awaited_once()
    assert detail.key == "AIOPS-1"
    assert detail.assignee == "Alice"
    assert detail.reporter == "Bob"
    assert detail.issue_type == "Service Request"
    assert detail.url == "https://jira.example.internal/browse/AIOPS-1"
    assert len(detail.comments) == 1
    assert detail.comments[0].author == "Alice"
    assert detail.comments[0].body == "Looking into it"


@pytest.mark.asyncio
async def test_fetch_ticket_detail_handles_unassigned_and_no_comments():
    jira = AsyncMock()
    jira.get_issue.return_value = {
        "key": "AIOPS-2",
        "fields": {
            "summary": "Unassigned ticket",
            "description": None,
            "status": {"name": "Open"},
            "priority": None,
            "issuetype": {"name": "Task"},
            "assignee": None,
            "reporter": None,
            "created": "2026-08-10T09:00:00.000+0000",
            "updated": "2026-08-10T09:00:00.000+0000",
        },
    }

    detail = await fetch_ticket_detail(jira, _settings(), "AIOPS-2")

    assert detail.assignee is None
    assert detail.reporter is None
    assert detail.priority is None
    assert detail.description == ""
    assert detail.comments == []


@pytest.mark.asyncio
async def test_fetch_issue_types_returns_jira_types_when_available():
    jira = AsyncMock()
    jira.get_create_issue_types.return_value = ["Service Request", "Task"]

    types = await fetch_issue_types(jira, _settings())

    assert types == ["Service Request", "Task"]


@pytest.mark.asyncio
async def test_fetch_issue_types_falls_back_when_jira_returns_none():
    jira = AsyncMock()
    jira.get_create_issue_types.return_value = []

    types = await fetch_issue_types(jira, _settings())

    assert types == FALLBACK_ISSUE_TYPES


@pytest.mark.asyncio
async def test_fetch_issue_types_falls_back_when_createmeta_unavailable():
    from app.jira_client import JiraClientError

    jira = AsyncMock()
    jira.get_create_issue_types.side_effect = JiraClientError("createmeta not supported on this instance")

    types = await fetch_issue_types(jira, _settings())

    assert types == FALLBACK_ISSUE_TYPES


@pytest.mark.asyncio
async def test_fetch_reporting_services_maps_entries():
    jira = AsyncMock()
    jira.search_insight_objects.return_value = [
        {"id": 1, "objectKey": "SD-1", "label": "Network"},
        {"id": 2, "objectKey": "SD-2", "label": "Email"},
    ]

    services = await fetch_reporting_services(
        jira, _settings(jira_reporting_service_field_id="customfield_14503")
    )

    assert len(services) == 2
    assert services[0].key == "SD-1"
    assert services[0].label == "Network"
    call_kwargs = jira.search_insight_objects.await_args.kwargs
    assert call_kwargs["object_type"] == "Service"
    assert call_kwargs["object_schema_id"] == 1


@pytest.mark.asyncio
async def test_fetch_reporting_services_skips_entries_missing_key_or_label():
    jira = AsyncMock()
    jira.search_insight_objects.return_value = [
        {"id": 1, "objectKey": "SD-1", "label": "Network"},
        {"id": 2, "objectKey": None, "label": "Broken"},
        {"id": 3, "objectKey": "SD-3", "label": ""},
    ]

    services = await fetch_reporting_services(jira, _settings())

    assert [s.key for s in services] == ["SD-1"]


@pytest.mark.asyncio
async def test_fetch_reporting_services_passes_through_query():
    jira = AsyncMock()
    jira.search_insight_objects.return_value = []

    await fetch_reporting_services(jira, _settings(), query="vpn")

    call_kwargs = jira.search_insight_objects.await_args.kwargs
    assert call_kwargs["query"] == "vpn"


@pytest.mark.asyncio
async def test_fetch_extra_select_fields_returns_empty_when_not_configured():
    jira = AsyncMock()

    fields = await fetch_extra_select_fields(jira, _settings())

    assert fields == []
    jira.get_editmeta.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_extra_select_fields_maps_allowed_values_and_drops_disabled():
    jira = AsyncMock()
    jira.get_editmeta.return_value = {
        "customfield_36200": {
            "name": "Subsidiary",
            "allowedValues": [
                {"id": "1", "value": "emaratech G", "disabled": False},
                {"id": "2", "value": "Retired Option", "disabled": True},
            ],
        },
        "customfield_32404": {
            "name": "SR Type",
            "allowedValues": [{"id": "10", "value": "IT Helpdesk", "disabled": False}],
        },
    }
    settings = _settings(
        jira_field_metadata_reference_issue="SDIMD-80022",
        jira_extra_select_fields={"customfield_36200": "Subsidiary", "customfield_32404": "SR Type"},
    )

    fields = await fetch_extra_select_fields(jira, settings)

    jira.get_editmeta.assert_awaited_once_with("SDIMD-80022")
    by_id = {f.field_id: f for f in fields}
    assert by_id["customfield_36200"].label == "Subsidiary"
    assert [o.value for o in by_id["customfield_36200"].options] == ["emaratech G"]
    assert [o.value for o in by_id["customfield_32404"].options] == ["IT Helpdesk"]


@pytest.mark.asyncio
async def test_fetch_extra_select_fields_skips_fields_missing_from_editmeta():
    jira = AsyncMock()
    jira.get_editmeta.return_value = {}
    settings = _settings(
        jira_field_metadata_reference_issue="SDIMD-80022",
        jira_extra_select_fields={"customfield_99999": "Unknown Field"},
    )

    fields = await fetch_extra_select_fields(jira, settings)

    assert fields == []


def test_approvals_jql_scopes_to_current_user_and_open_status():
    jql = approvals_jql(_settings())
    assert "assignee = currentUser()" in jql
    assert "statusCategory != Done" in jql


def test_approvals_jql_ors_in_configured_approver_fields():
    jql = approvals_jql(_settings(jira_approver_fields=["customfield_25502"]))
    assert "assignee = currentUser()" in jql
    assert "cf[25502] = currentUser()" in jql
    assert " OR " in jql


def test_approvals_jql_omits_approver_clause_when_not_configured():
    jql = approvals_jql(_settings())
    assert "cf[" not in jql


@pytest.mark.asyncio
async def test_fetch_approval_tickets_only_includes_tickets_with_an_approval_transition():
    jira = AsyncMock()
    jira.search_issues.return_value = {
        "issues": [
            {
                "key": "SDIMD-1",
                "fields": {
                    "summary": "Hardware request",
                    "status": {"name": "Pending Line Manager"},
                    "issuetype": {"name": "IT Set Up - Hardware"},
                    "reporter": {"displayName": "Ilyas Ahmed"},
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            },
            {
                "key": "SDIMD-2",
                "fields": {
                    "summary": "Ordinary in-progress ticket",
                    "status": {"name": "Work in progress"},
                    "issuetype": {"name": "Task"},
                    "reporter": None,
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            },
        ]
    }
    jira.get_transitions.side_effect = [
        [
            {"id": "21", "name": "Approve", "to": {"name": "IMD Domain Approval"}},
            {"id": "41", "name": "Reject", "to": {"name": "Open"}},
        ],
        [{"id": "11", "name": "Start Progress", "to": {"name": "In Progress"}}],
    ]

    tickets = await fetch_approval_tickets(jira, _settings(jira_base_url="https://jira.example.internal"))

    assert [t.key for t in tickets] == ["SDIMD-1"]
    assert tickets[0].reporter == "Ilyas Ahmed"
    assert tickets[0].url == "https://jira.example.internal/browse/SDIMD-1"
    assert [t.name for t in tickets[0].transitions] == ["Approve", "Reject"]


@pytest.mark.parametrize(
    "raw_fields,expected",
    [
        ({}, []),
        (
            {
                "customfield_32700": {
                    "required": False,
                    "schema": {"type": "number", "customId": 32700},
                    "name": "Estimated Hrs.",
                }
            },
            [("customfield_32700", "Estimated Hrs.", "number")],
        ),
        (
            {"customfield_14100": {"schema": {"type": "string"}, "name": "Rejection Reason"}},
            [("customfield_14100", "Rejection Reason", "string")],
        ),
        # Unsupported schema types (select/user picker/etc.) are dropped --
        # Jira's own error is still the fallback if one turns out required.
        ({"customfield_1": {"schema": {"type": "option"}, "name": "Resolution"}}, []),
        ({"customfield_2": {"schema": {}, "name": "No type"}}, []),
    ],
)
def test_transition_extra_fields(raw_fields, expected):
    specs = _transition_extra_fields(raw_fields)
    assert [(s.field_id, s.label, s.type) for s in specs] == expected


@pytest.mark.asyncio
async def test_fetch_approval_tickets_surfaces_extra_transition_fields():
    jira = AsyncMock()
    jira.search_issues.return_value = {
        "issues": [
            {
                "key": "SDSEC-1",
                "fields": {
                    "summary": "Software request",
                    "status": {"name": "Pending Security Review"},
                    "issuetype": {"name": "IT Set Up - Software"},
                    "reporter": None,
                    "updated": "2026-08-15T10:00:00.000+0000",
                },
            }
        ]
    }
    jira.get_transitions.return_value = [
        {
            "id": "91",
            "name": "Approve",
            "to": {"name": "In Implementation"},
            "fields": {
                "customfield_32700": {"schema": {"type": "number"}, "name": "Estimated Hrs."}
            },
        }
    ]

    tickets = await fetch_approval_tickets(jira, _settings())

    extra = tickets[0].transitions[0].extra_fields
    assert len(extra) == 1
    assert extra[0].field_id == "customfield_32700"
    assert extra[0].label == "Estimated Hrs."
    assert extra[0].type == "number"


@pytest.mark.asyncio
async def test_fetch_approval_tickets_empty_when_no_candidates():
    jira = AsyncMock()
    jira.search_issues.return_value = {"issues": []}

    tickets = await fetch_approval_tickets(jira, _settings())

    assert tickets == []
    jira.get_transitions.assert_not_awaited()


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ([], None),
        ({}, None),
        (True, "Yes"),
        (False, "No"),
        (5, "5"),
        ("Production", "Production"),
        ({"value": "Medium"}, "Medium"),
        ({"displayName": "Alice"}, "Alice"),
        ({"id": "35", "name": "Time to resolution", "completedCycles": []}, None),
        ('<a href="https://jira/x">link</a>', None),
        ([{"value": "A"}, {"value": "B"}], "A, B"),
        ([{"value": "A"}, None], "A"),
    ],
)
def test_flatten_field_value(value, expected):
    assert _flatten_field_value(value) == expected


def test_is_substantive_rejects_empty_wiki_tables_and_accepts_real_content():
    assert _is_substantive("||1|| || || || ||") is False
    assert _is_substantive("||Col||\r\n|| || ||") is False
    assert _is_substantive("||Reason||\r\n||Memory at 90% on bhmanwsus01||") is True


@pytest.mark.asyncio
async def test_fetch_approval_detail_maps_core_fields_and_filters_junk_customfields():
    jira = AsyncMock()
    jira.get_issue.return_value = {
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
            "customfield_30404": "||Col||\r\n|| || ||",
            "customfield_30403": "||Reason||\r\n||Memory at 90% on bhmanwsus01||",
            "attachment": [
                {
                    "id": "2500704",
                    "filename": "network-access.xlsx",
                    "size": 166912,
                    "mimeType": "application/octet-stream",
                    "author": {"displayName": "Shakeeb Ullah"},
                    "created": "2026-08-19T11:35:08.015+0400",
                    "content": "https://jira.example.internal/secure/attachment/2500704/network-access.xlsx",
                }
            ],
        },
    }
    jira.get_fields.return_value = [
        {"id": "customfield_13657", "name": "Environment"},
        {"id": "customfield_30403", "name": "Upgrade Compute (Existing VM) Description"},
    ]
    jira.get_transitions.return_value = [
        {"id": "21", "name": "Approve", "to": {"name": "IMD Domain Approval"}},
    ]

    detail = await fetch_approval_detail(
        jira, _settings(jira_base_url="https://jira.example.internal"), "SDIMD-74126"
    )

    assert detail.key == "SDIMD-74126"
    assert detail.assignee == "Mayilvahanan T"
    assert detail.reporter == "Ilyas Ahmed"
    assert detail.url == "https://jira.example.internal/browse/SDIMD-74126"
    by_label = {f.label: f.value for f in detail.fields}
    assert by_label["Environment"] == "Production"
    assert by_label["Upgrade Compute (Existing VM) Description"] == "||Reason||\r\n||Memory at 90% on bhmanwsus01||"
    assert "customfield_36819" not in by_label
    assert "customfield_30404" not in by_label
    assert [t.name for t in detail.transitions] == ["Approve"]
    assert len(detail.attachments) == 1
    assert detail.attachments[0].filename == "network-access.xlsx"
    assert detail.attachments[0].url == "https://jira.example.internal/secure/attachment/2500704/network-access.xlsx"
