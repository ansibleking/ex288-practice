from __future__ import annotations

from typing import Any

from tams_mcp.config import Settings, get_settings


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


def build_report_payload(settings: Settings | None = None, **overrides: Any) -> dict[str, Any]:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "payCode": settings.tams_paycode,
        "companyCode": settings.tams_company_code,
        "auth_comp": settings.tams_auth_comp,
        "auth_dept": settings.tams_auth_dept,
        "auth_location": settings.tams_auth_loc,
        "auth_site": settings.tams_auth_site,
        "userType": settings.tams_user_type,
    }
    payload.update({k: v for k, v in overrides.items() if v is not None})
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
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return payload


def merge_with_login(login: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Connect_API expects login fields embedded in POST bodies."""
    merged = {**login, **body}
    if "usertype" in merged and "userType" not in body:
        merged["userType"] = merged["usertype"]
    return merged
