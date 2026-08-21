from __future__ import annotations

from datetime import date
from typing import Any

from tams_mcp.config import Settings, get_settings

REPORT_SCOPE_KEYS = frozenset(
    {
        "auth_comp",
        "auth_dept",
        "auth_location",
        "auth_site",
        "userType",
        "usertype",
        "companyCode",
        "payCode",
        "paycode",
    }
)


MONTHLY_REPORT_DEFAULTS: dict[str, str] = {
    "g_Company": "*",
    "g_Department": "*",
    "g_Location": "*",
    "g_Category": "*",
    "g_Shift": "*",
    "g_Employee": "*",
    "g_Grade": "*",
    "g_Designation": "*",
    "g_Site": "*",
    "g_Section": "*",
}



def format_tams_date(value: Any) -> str:
    """Connect_API report endpoints expect dd/MM/yyyy, not ISO dates."""
    if value is None:
        return ""
    if isinstance(value, str):
        if "/" in value:
            return value
        return date.fromisoformat(value[:10]).strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def build_login_payload(settings: Settings | None = None, **overrides: Any) -> dict[str, Any]:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "useR_R": settings.tams_username,
        "password": settings.tams_password,
        "paycode": settings.tams_paycode,
        "payCode": settings.tams_paycode,
        "companyCode": settings.tams_company_code,
        "auth_comp": settings.tams_auth_comp,
        "auth_dept": settings.tams_auth_dept,
        "auth_location": settings.tams_auth_loc,
        "auth_site": settings.tams_auth_site,
        "usertype": settings.tams_user_type,
        "userType": settings.tams_user_type,
        "loginLanguage": "en",
        "loginType": "ESS",
    }
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return payload



def build_report_payload(
    settings: Settings | None = None,
    *,
    monthly: bool = False,

    **overrides: Any,
) -> dict[str, Any]:
    settings = settings or get_settings()
    scope = {
        "companyCode": settings.tams_company_code,
        "auth_comp": settings.tams_auth_comp,
        "auth_dept": settings.tams_auth_dept,
        "auth_location": settings.tams_auth_loc,
        "auth_site": settings.tams_auth_site,
        "userType": settings.tams_user_type,
    }

    for key, value in overrides.items():
        if value is None:
            continue
        if key in {"fromDate", "toDate", "dashboardDate"}:
            normalized[key] = format_tams_date(value)
        else:
            normalized[key] = value
    payload.update(normalized)


def build_correction_payload(settings: Settings | None = None, **overrides: Any) -> dict[str, Any]:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "paycode": settings.tams_paycode,
        "company": settings.tams_company_code,
        "auth_comp": settings.tams_auth_comp,
        "auth_dept": settings.tams_auth_dept,
        "auth_loc": settings.tams_auth_loc,
        "auth_site": settings.tams_auth_site,
        "userType": settings.tams_user_type,
    }
    for key, value in overrides.items():
        if value is None:
            continue
        if key in {"fromDate", "toDate"}:
            payload[key] = format_tams_date(value)
        else:
            payload[key] = value
    return payload


def merge_with_login(login: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Full login payload merge — only for /login/* endpoints."""
    merged = {**login, **body}
    if "usertype" in merged and "userType" not in body:
        merged["userType"] = merged["usertype"]
    return merged



    merged = {**scope, **body}
    if "usertype" in merged and "userType" not in body:
        merged["userType"] = merged["usertype"]
    return merged
