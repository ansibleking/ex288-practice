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

PROFILE_SCOPE_MAP: dict[str, str] = {
    "auth_comp": "auth_comp",
    "auth_dept": "auth_dept",
    "auth_location": "auth_location",
    "auth_site": "auth_site",
    "companyCode": "companyCode",
    "paycode": "payCode",
    "payCode": "payCode",
    "usertype": "userType",
    "userType": "userType",
}

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


def current_month_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return today.replace(day=1), today


def apply_default_dates(args: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Fill missing fromDate/toDate with the current calendar month."""
    args = dict(args)
    start, end = current_month_range(today)
    if not args.get("fromDate"):
        args["fromDate"] = start
    if not args.get("toDate"):
        args["toDate"] = end
    return args


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


def resolve_report_scope(login_context: dict[str, Any] | None) -> dict[str, Any]:
    """Prefer auth scope returned by GetLoginDetails over static .env values."""
    login_context = login_context or {}
    login = login_context.get("login") or build_login_payload()
    profile = login_context.get("profile") if isinstance(login_context.get("profile"), dict) else {}

    scope: dict[str, Any] = {}
    for profile_key, body_key in PROFILE_SCOPE_MAP.items():
        value = profile.get(profile_key)
        if value not in (None, ""):
            scope[body_key] = value

    for key in REPORT_SCOPE_KEYS:
        if scope.get(key) in (None, ""):
            value = login.get(key)
            if value not in (None, ""):
                scope[key] = value

    if scope.get("usertype") and not scope.get("userType"):
        scope["userType"] = scope["usertype"]
    return scope


def build_report_payload(
    settings: Settings | None = None,
    *,
    monthly: bool = False,
    all_employees: bool = False,
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
    if not all_employees:
        scope["payCode"] = settings.tams_paycode
    payload: dict[str, Any] = dict(scope)
    if monthly:
        payload.update(MONTHLY_REPORT_DEFAULTS)

    normalized: dict[str, Any] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        if key in {"fromDate", "toDate", "dashboardDate"}:
            normalized[key] = format_tams_date(value)
        else:
            normalized[key] = value
    payload.update(normalized)

    if all_employees and "payCode" not in normalized:
        payload.pop("payCode", None)
        payload["g_Employee"] = "*"

    return payload


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


def merge_report_scope(login_context: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    """Report models reject unknown fields (additionalProperties=false)."""
    scope = resolve_report_scope(login_context)
    merged = {**scope, **body}
    if "usertype" in merged and "userType" not in body:
        merged["userType"] = merged["usertype"]
    return merged
