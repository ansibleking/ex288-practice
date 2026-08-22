from __future__ import annotations

from tams_mcp.auth import AuthConfig, TamsAuthManager
from tams_mcp.config import get_settings
from tams_mcp.context import build_report_payload, current_month_range, resolve_report_scope
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
        scope = resolve_report_scope(await client.auth.ensure_login())
        print(
            "Auth scope: "
            f"comp={'set' if scope.get('auth_comp') else 'missing'}, "
            f"dept={'set' if scope.get('auth_dept') else 'missing'}, "
            f"loc={'set' if scope.get('auth_location') else 'missing'}, "
            f"site={'set' if scope.get('auth_site') else 'missing'}"
        )

        start, end = current_month_range()
        result = await client.post(
            "/MonthlyReports/GetEmployeeWiseAttendance",
            json_body=build_report_payload(
                monthly=True,
                all_employees=True,
                fromDate=start,
                toDate=end,
            ),
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

