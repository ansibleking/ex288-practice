from __future__ import annotations

import asyncio

from tams_mcp.auth import AuthConfig, TamsAuthManager
from tams_mcp.config import get_settings
from tams_mcp.tams_client import TamsApiError, TamsClient

_session_client: TamsClient | None = None


def get_session_client() -> TamsClient:
    global _session_client
    if _session_client is None:
        settings = get_settings()
        auth = TamsAuthManager(
            AuthConfig(
                mode=settings.tams_auth_mode,  # type: ignore[arg-type]
                tenant_id=settings.azure_tenant_id,
                client_id=settings.azure_client_id,
                client_secret=settings.azure_client_secret,
                scope=settings.tams_api_scope,
                static_token=settings.tams_access_token,
            )
        )
        _session_client = TamsClient(settings.tams_base_url, auth)
    return _session_client


async def check_tams_auth() -> int:
    settings = get_settings()
    client = get_session_client()

    print(f"TAMS base URL: {settings.tams_base_url}")
    print(f"Auth mode: {settings.tams_auth_mode}")
    print(f"Username set: {'yes' if settings.tams_username else 'no'}")
    print(f"Bearer token set: {'yes' if settings.tams_access_token else 'no'}")
    print(f"Session cookie set: {'yes' if settings.tams_session_cookie else 'no'}")

    try:
        ctx = await client.auth.ensure_login()
        mode = ctx.get("mode", settings.tams_auth_mode)
        print(f"Login step: OK ({mode}, cookies={client.cookie_count()})")
    except Exception as exc:
        print(f"Login step: FAILED ({exc})")
        return 1

    try:
        from datetime import date

        today = date.today()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()
        result = await client.post(
            "/MonthlyReports/GetEmployeeWiseAttendance",
            json_body={"fromDate": start, "toDate": end},
        )
        if isinstance(result, dict) and result.get("error"):
            print(f"Report call: FAILED ({result})")
            return 1
        print(f"Report call: OK (cookies={client.cookie_count()})")
        return 0
    except TamsApiError as exc:
        print(f"Report call: FAILED ({exc})")
        return 1
    except Exception as exc:
        print(f"Report call: FAILED ({exc})")
        return 1


def reset_session_client() -> None:
    global _session_client
    if _session_client is not None:
        asyncio.get_event_loop().create_task(_session_client.aclose())
    _session_client = None
