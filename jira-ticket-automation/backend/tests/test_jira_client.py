import json

import httpx
import pytest
import respx

from app.config import Settings
from app.jira_client import JiraClient, JiraClientError

BASE_URL = "https://jira.example.internal"


def _settings() -> Settings:
    return Settings(
        jira_base_url=BASE_URL,
        jira_pat="test-token",
        jira_project_key="AIOPS",
        anthropic_api_key="test-anthropic-key",
    )


@pytest.mark.asyncio
async def test_whoami_sends_bearer_auth():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/myself").mock(
            return_value=httpx.Response(200, json={"displayName": "Service Account"})
        )
        client = JiraClient(_settings())
        try:
            me = await client.whoami()
        finally:
            await client.aclose()

        assert route.called
        assert route.calls[0].request.headers["authorization"] == "Bearer test-token"
        assert me["displayName"] == "Service Account"


@pytest.mark.asyncio
async def test_search_issues_sends_jql_params():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/search").mock(
            return_value=httpx.Response(200, json={"issues": [{"key": "AIOPS-1"}]})
        )
        client = JiraClient(_settings())
        try:
            result = await client.search_issues('labels = "aiops-managed"', ["summary"])
        finally:
            await client.aclose()

        assert route.called
        assert "jql=labels" in str(route.calls[0].request.url)
        assert result["issues"][0]["key"] == "AIOPS-1"


@pytest.mark.asyncio
async def test_create_issue_posts_expected_payload():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue").mock(
            return_value=httpx.Response(201, json={"id": "10000", "key": "AIOPS-42"})
        )
        client = JiraClient(_settings())
        try:
            result = await client.create_issue(
                project_key="AIOPS",
                issue_type="Task",
                summary="DB pool exhaustion",
                description="Seeing intermittent 503s",
                labels=["aiops-managed"],
            )
        finally:
            await client.aclose()

        assert route.called
        body = json.loads(route.calls[0].request.content)
        assert body["fields"]["project"] == {"key": "AIOPS"}
        assert body["fields"]["issuetype"] == {"name": "Task"}
        assert body["fields"]["labels"] == ["aiops-managed"]
        assert result["key"] == "AIOPS-42"


@pytest.mark.asyncio
async def test_create_issue_merges_extra_fields_into_payload():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue").mock(
            return_value=httpx.Response(201, json={"id": "10001", "key": "AIOPS-43"})
        )
        client = JiraClient(_settings())
        try:
            await client.create_issue(
                project_key="AIOPS",
                issue_type="Service Request",
                summary="VPN access",
                description="New contractor",
                labels=["aiops-managed"],
                extra_fields={"customfield_14503": {"value": "IT Infrastructure"}},
            )
        finally:
            await client.aclose()

        body = json.loads(route.calls[0].request.content)
        assert body["fields"]["customfield_14503"] == {"value": "IT Infrastructure"}
        assert body["fields"]["project"] == {"key": "AIOPS"}


@pytest.mark.asyncio
async def test_add_comment_posts_body():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/comment").mock(
            return_value=httpx.Response(201, json={"id": "10001"})
        )
        client = JiraClient(_settings())
        try:
            result = await client.add_comment("AIOPS-1", "resolved")
        finally:
            await client.aclose()

        assert route.called
        assert json.loads(route.calls[0].request.content) == {"body": "resolved"}
        assert result["id"] == "10001"


@pytest.mark.asyncio
async def test_add_worklog_posts_time_spent_and_comment():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/worklog").mock(
            return_value=httpx.Response(201, json={"id": "20001"})
        )
        client = JiraClient(_settings())
        try:
            await client.add_worklog("AIOPS-1", "5m", "AI-triaged update")
        finally:
            await client.aclose()

        assert route.called
        assert json.loads(route.calls[0].request.content) == {
            "timeSpent": "5m",
            "comment": "AI-triaged update",
        }


@pytest.mark.asyncio
async def test_find_transition_id_matches_by_status_name_case_insensitive():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/issue/AIOPS-1/transitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "transitions": [
                        {"id": "11", "to": {"name": "In Progress"}},
                        {"id": "31", "to": {"name": "Done"}},
                    ]
                },
            )
        )
        client = JiraClient(_settings())
        try:
            transition_id = await client.find_transition_id("AIOPS-1", "done")
        finally:
            await client.aclose()

        assert transition_id == "31"


@pytest.mark.asyncio
async def test_find_transition_id_returns_none_when_no_match():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/issue/AIOPS-1/transitions").mock(
            return_value=httpx.Response(
                200, json={"transitions": [{"id": "11", "to": {"name": "In Progress"}}]}
            )
        )
        client = JiraClient(_settings())
        try:
            transition_id = await client.find_transition_id("AIOPS-1", "Done")
        finally:
            await client.aclose()

        assert transition_id is None


@pytest.mark.asyncio
async def test_do_transition_posts_transition_id():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/transitions").mock(return_value=httpx.Response(204))
        client = JiraClient(_settings())
        try:
            await client.do_transition("AIOPS-1", "31")
        finally:
            await client.aclose()

        assert route.called
        assert json.loads(route.calls[0].request.content) == {"transition": {"id": "31"}}


@pytest.mark.asyncio
async def test_do_transition_includes_comment_when_given():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/transitions").mock(return_value=httpx.Response(204))
        client = JiraClient(_settings())
        try:
            await client.do_transition("AIOPS-1", "31", comment="Approved, looks routine.")
        finally:
            await client.aclose()

        assert route.called
        assert json.loads(route.calls[0].request.content) == {
            "transition": {"id": "31"},
            "update": {"comment": [{"add": {"body": "Approved, looks routine."}}]},
        }


@pytest.mark.asyncio
async def test_do_transition_includes_fields_when_given():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/transitions").mock(return_value=httpx.Response(204))
        client = JiraClient(_settings())
        try:
            await client.do_transition("AIOPS-1", "31", fields={"customfield_32700": 4})
        finally:
            await client.aclose()

        assert route.called
        assert json.loads(route.calls[0].request.content) == {
            "transition": {"id": "31"},
            "fields": {"customfield_32700": 4},
        }


@pytest.mark.asyncio
async def test_get_transitions_requests_fields_expansion():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/issue/AIOPS-1/transitions").mock(
            return_value=httpx.Response(200, json={"transitions": []})
        )
        client = JiraClient(_settings())
        try:
            await client.get_transitions("AIOPS-1")
        finally:
            await client.aclose()

        assert route.called
        assert "expand=transitions.fields" in str(route.calls[0].request.url)


@pytest.mark.asyncio
async def test_get_issue_requests_specified_fields():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/issue/AIOPS-1").mock(
            return_value=httpx.Response(200, json={"key": "AIOPS-1", "fields": {"summary": "s"}})
        )
        client = JiraClient(_settings())
        try:
            result = await client.get_issue("AIOPS-1", ["summary", "status"])
        finally:
            await client.aclose()

        assert route.called
        assert "fields=summary%2Cstatus" in str(route.calls[0].request.url)
        assert result["key"] == "AIOPS-1"


@pytest.mark.asyncio
async def test_get_fields_returns_field_definitions():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/field").mock(
            return_value=httpx.Response(
                200, json=[{"id": "customfield_100", "name": "Subsidiary"}]
            )
        )
        client = JiraClient(_settings())
        try:
            fields = await client.get_fields()
        finally:
            await client.aclose()

        assert route.called
        assert fields == [{"id": "customfield_100", "name": "Subsidiary"}]


@pytest.mark.asyncio
async def test_get_editmeta_returns_fields_dict():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.get("/issue/AIOPS-1/editmeta").mock(
            return_value=httpx.Response(
                200,
                json={
                    "fields": {
                        "customfield_100": {
                            "required": False,
                            "name": "Subsidiary",
                            "allowedValues": [{"id": "1", "value": "A", "disabled": False}],
                        }
                    }
                },
            )
        )
        client = JiraClient(_settings())
        try:
            fields = await client.get_editmeta("AIOPS-1")
        finally:
            await client.aclose()

        assert route.called
        assert fields["customfield_100"]["name"] == "Subsidiary"


@pytest.mark.asyncio
async def test_add_attachment_posts_multipart_with_no_check_header():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        route = mock.post("/issue/AIOPS-1/attachments").mock(
            return_value=httpx.Response(
                200, json=[{"id": "10001", "filename": "screenshot.png"}]
            )
        )
        client = JiraClient(_settings())
        try:
            result = await client.add_attachment(
                "AIOPS-1", filename="screenshot.png", content=b"fake-bytes", content_type="image/png"
            )
        finally:
            await client.aclose()

        assert route.called
        request = route.calls[0].request
        assert request.headers["x-atlassian-token"] == "no-check"
        assert b"screenshot.png" in request.content
        assert b"fake-bytes" in request.content
        assert result[0]["filename"] == "screenshot.png"


@pytest.mark.asyncio
async def test_get_create_issue_types_parses_names():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/issue/createmeta").mock(
            return_value=httpx.Response(
                200,
                json={
                    "projects": [
                        {
                            "key": "AIOPS",
                            "issuetypes": [{"name": "Service Request"}, {"name": "Task"}, {"name": "Bug"}],
                        }
                    ]
                },
            )
        )
        client = JiraClient(_settings())
        try:
            types = await client.get_create_issue_types("AIOPS")
        finally:
            await client.aclose()

        assert types == ["Service Request", "Task", "Bug"]


@pytest.mark.asyncio
async def test_get_create_issue_types_returns_empty_when_no_projects():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/issue/createmeta").mock(return_value=httpx.Response(200, json={"projects": []}))
        client = JiraClient(_settings())
        try:
            types = await client.get_create_issue_types("AIOPS")
        finally:
            await client.aclose()

        assert types == []


@pytest.mark.asyncio
async def test_search_insight_objects_builds_iql_and_hits_insight_api():
    async with respx.mock(base_url=f"{BASE_URL}/rest/insight/1.0") as mock:
        route = mock.get("/iql/objects").mock(
            return_value=httpx.Response(
                200,
                json={
                    "objectEntries": [
                        {"id": 1, "objectKey": "SD-1", "label": "Network"},
                        {"id": 2, "objectKey": "SD-2", "label": "Email"},
                    ]
                },
            )
        )
        client = JiraClient(_settings())
        try:
            entries = await client.search_insight_objects(object_type="Service", object_schema_id=1)
        finally:
            await client.aclose()

        assert route.called
        sent_iql = httpx.QueryParams(route.calls[0].request.url.query.decode())["iql"]
        assert sent_iql == 'objectType = "Service"'
        assert len(entries) == 2
        assert entries[0]["objectKey"] == "SD-1"


@pytest.mark.asyncio
async def test_search_insight_objects_adds_name_filter_when_query_given():
    async with respx.mock(base_url=f"{BASE_URL}/rest/insight/1.0") as mock:
        route = mock.get("/iql/objects").mock(return_value=httpx.Response(200, json={"objectEntries": []}))
        client = JiraClient(_settings())
        try:
            await client.search_insight_objects(object_type="Service", object_schema_id=1, query="vpn")
        finally:
            await client.aclose()

        sent_iql = httpx.QueryParams(route.calls[0].request.url.query.decode())["iql"]
        assert sent_iql == 'objectType = "Service" AND Name like "vpn"'


@pytest.mark.asyncio
async def test_search_insight_objects_escapes_quotes_in_query():
    async with respx.mock(base_url=f"{BASE_URL}/rest/insight/1.0") as mock:
        route = mock.get("/iql/objects").mock(return_value=httpx.Response(200, json={"objectEntries": []}))
        client = JiraClient(_settings())
        try:
            await client.search_insight_objects(object_type="Service", object_schema_id=1, query='a" OR "1"="1')
        finally:
            await client.aclose()

        # The raw quote must not appear unescaped in the outgoing IQL.
        sent_iql = httpx.QueryParams(route.calls[0].request.url.query.decode())["iql"]
        assert 'a\\" OR \\"1\\"=\\"1' in sent_iql


@pytest.mark.asyncio
async def test_error_response_raises_jira_client_error():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/issue/AIOPS-404/transitions").mock(
            return_value=httpx.Response(404, text="not found")
        )
        client = JiraClient(_settings())
        try:
            with pytest.raises(JiraClientError):
                await client.get_transitions("AIOPS-404")
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_network_failure_raises_jira_client_error():
    async with respx.mock(base_url=f"{BASE_URL}/rest/api/2") as mock:
        mock.get("/myself").mock(side_effect=httpx.ConnectError("Name or service not known"))
        client = JiraClient(_settings())
        try:
            with pytest.raises(JiraClientError):
                await client.whoami()
        finally:
            await client.aclose()
