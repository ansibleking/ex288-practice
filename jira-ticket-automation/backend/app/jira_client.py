from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class JiraClientError(RuntimeError):
    """Raised when the Jira DC REST API returns an unexpected response."""


class JiraClient:
    """Thin async wrapper around the Jira Data Center REST API v2.

    Authenticated with a service-account Personal Access Token via Bearer
    auth. Unlike the sibling network-access-review tool, this client never
    downloads attachments -- every call here is a plain /rest/api/2/* REST
    endpoint, which is unaffected by the attachment-download auth quirks
    that instance has on the legacy /secure/attachment/... path.
    """

    def __init__(self, settings: Settings):
        base_url = settings.jira_base_url.rstrip("/")
        self._insight_base = f"{base_url}/rest/insight/1.0"
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/rest/api/2",
            headers={"Authorization": f"Bearer {settings.jira_pat}"},
            timeout=settings.request_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise JiraClientError(f"Jira API {method} {url} unreachable: {exc}") from exc
        if response.is_error:
            raise JiraClientError(
                f"Jira API {method} {url} failed: {response.status_code} {response.text[:500]}"
            )
        return response

    async def whoami(self) -> dict[str, Any]:
        response = await self._request("GET", "/myself")
        return response.json()

    async def get_issue(self, key: str, fields: list[str]) -> dict[str, Any]:
        response = await self._request("GET", f"/issue/{key}", params={"fields": ",".join(fields)})
        return response.json()

    async def get_editmeta(self, key: str) -> dict[str, Any]:
        """Per-field metadata (including allowedValues for select fields) for
        an existing issue. createmeta is unavailable on this Jira DC instance
        (404), and Jira DC has no generic "list options for field X"
        endpoint, so a known-good reference issue's editmeta is the only
        reliable way found to discover a select field's real option list.
        """
        response = await self._request("GET", f"/issue/{key}/editmeta")
        return response.json().get("fields", {})

    async def get_fields(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/field")
        return response.json()

    async def get_create_issue_types(self, project_key: str) -> list[str]:
        response = await self._request(
            "GET",
            "/issue/createmeta",
            params={"projectKeys": project_key, "expand": "projects.issuetypes"},
        )
        projects = response.json().get("projects", [])
        if not projects:
            return []
        return [t["name"] for t in projects[0].get("issuetypes", [])]

    async def search_insight_objects(
        self, object_type: str, object_schema_id: int, query: str | None = None, result_per_page: int = 500
    ) -> list[dict[str, Any]]:
        """Search Insight/Assets catalog objects (e.g. a "Service" catalog).

        Insight lives under /rest/insight/1.0/, a separate API from the
        standard /rest/api/2/ Jira REST API used everywhere else in this
        client -- these object references are what some custom fields (e.g.
        a JSM "Reporting Service" field) expect instead of a plain string.
        """
        escaped_type = object_type.replace("\\", "\\\\").replace('"', '\\"')
        iql = f'objectType = "{escaped_type}"'
        if query:
            escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
            iql += f' AND Name like "{escaped_query}"'
        response = await self._request(
            "GET",
            f"{self._insight_base}/iql/objects",
            params={"iql": iql, "objectSchemaId": object_schema_id, "resultPerPage": result_per_page},
        )
        return response.json().get("objectEntries", [])

    async def search_issues(
        self, jql: str, fields: list[str], start_at: int = 0, max_results: int = 50
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "/search",
            params={
                "jql": jql,
                "fields": ",".join(fields),
                "startAt": start_at,
                "maxResults": max_results,
            },
        )
        return response.json()

    async def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        labels: list[str],
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": description,
            "labels": labels,
        }
        if extra_fields:
            fields.update(extra_fields)
        response = await self._request("POST", "/issue", json={"fields": fields})
        return response.json()

    async def add_attachment(
        self, key: str, filename: str, content: bytes, content_type: str
    ) -> list[dict[str, Any]]:
        # Jira's attachment upload requires this header (a CSRF check it
        # otherwise applies to all POSTs) and rejects the call without it,
        # independent of Bearer auth being valid.
        response = await self._request(
            "POST",
            f"/issue/{key}/attachments",
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (filename, content, content_type)},
        )
        return response.json()

    async def add_comment(self, key: str, body: str) -> dict[str, Any]:
        response = await self._request("POST", f"/issue/{key}/comment", json={"body": body})
        return response.json()

    async def add_worklog(self, key: str, time_spent: str, comment: str) -> dict[str, Any]:
        payload = {"timeSpent": time_spent, "comment": comment}
        response = await self._request("POST", f"/issue/{key}/worklog", json=payload)
        return response.json()

    async def get_transitions(self, key: str) -> list[dict[str, Any]]:
        # expand=transitions.fields surfaces any extra fields a transition's
        # screen requires (e.g. a numeric "Estimated Hrs." field on some
        # approval transitions) -- without it, a required-field rejection on
        # POST /transitions only appears at submit time with no way to have
        # asked for it upfront.
        response = await self._request(
            "GET", f"/issue/{key}/transitions", params={"expand": "transitions.fields"}
        )
        return response.json().get("transitions", [])

    async def find_transition_id(self, key: str, target_status_name: str) -> str | None:
        transitions = await self.get_transitions(key)
        for t in transitions:
            if t["to"]["name"].lower() == target_status_name.lower():
                return t["id"]
        return None

    async def do_transition(
        self,
        key: str,
        transition_id: str,
        comment: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        # Some transition screens require a comment (e.g. "Reject", "Require
        # Clarifications") -- Jira DC doesn't reliably expose that
        # requirement via the transitions metadata endpoint, so it only
        # surfaces as a 400 "Comment is required" on the attempt itself.
        # Other screens require ordinary fields (e.g. "Estimated Hrs."),
        # which the fields param carries through as Jira's transition
        # payload does: {"transition": ..., "fields": {...}}.
        body: dict[str, Any] = {"transition": {"id": transition_id}}
        if fields:
            body["fields"] = fields
        if comment:
            body["update"] = {"comment": [{"add": {"body": comment}}]}
        await self._request("POST", f"/issue/{key}/transitions", json=body)
