from __future__ import annotations

from typing import Any

from mcp.types import Tool

from tams_mcp.context import apply_default_dates, build_correction_payload, build_login_payload, build_report_payload
from tams_mcp.swagger_loader import GeneratedTool
from tams_mcp.tams_client import TamsClient


def curated_tools() -> list[Tool]:
    return [
        Tool(
            name="get_daily_attendance",
            description="Daily attendance report for a date range (Connect_API DailyReports/GetDailyAttendance).",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Defaults to first day of current month",
                    },
                    "to_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Defaults to today",
                    },
                    "pay_code": {"type": "string", "description": "Employee pay code; defaults to TAMS_PAYCODE"},
                    "company_code": {"type": "string"},
                    "department": {"type": "string"},
                },
            },
        ),
        Tool(
            name="get_employee_wise_attendance",
            description=(
                "Monthly employee-wise attendance summary for all employees in scope. "
                "Defaults: current calendar month, all employees (no pay_code needed)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Optional; defaults to first day of current month",
                    },
                    "to_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Optional; defaults to today",
                    },
                    "pay_code": {
                        "type": "string",
                        "description": "Optional filter for one employee; omit for all employees",
                    },
                    "department": {"type": "string", "description": "Optional department filter"},
                },
            },
        ),
        Tool(
            name="get_attendance_correction",
            description="Fetch attendance correction records for an employee/date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "format": "date"},
                    "to_date": {"type": "string", "format": "date"},
                    "paycode": {"type": "string"},
                    "enrollment_code": {"type": "string"},
                },
                "required": ["from_date", "to_date"],
            },
        ),
        Tool(
            name="get_punch_activity",
            description="ESS punch activity for an employee (login/GetESSPunchActivity).",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "format": "date"},
                    "to_date": {"type": "string", "format": "date"},
                    "ssn": {"type": "string", "description": "Employee SSN/card number"},
                },
                "required": ["from_date", "to_date"],
            },
        ),
        Tool(
            name="get_leave_balance",
            description="Leave balance report (LeaveReports/GetBalanceLeave).",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "format": "date"},
                    "to_date": {"type": "string", "format": "date"},
                    "pay_code": {"type": "string"},
                },
                "required": ["from_date", "to_date"],
            },
        ),
        Tool(
            name="get_employee_attendance_list",
            description="Employee attendance list from data maintenance module.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "format": "date"},
                    "to_date": {"type": "string", "format": "date"},
                    "pay_code": {"type": "string"},
                },
                "required": ["from_date", "to_date"],
            },
        ),
        Tool(
            name="get_attendance_dashboard",
            description="Attendance dashboard metrics (login/GetAttendanceDashboard).",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_date": {"type": "string", "format": "date"},
                    "company_code": {"type": "string"},
                },
            },
        ),
        Tool(
            name="search_employees",
            description="Search/list employees (Employee/GetAllEmployee).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pay_code": {"type": "string"},
                    "department": {"type": "string"},
                    "search": {"type": "string"},
                },
            },
        ),
    ]


CURATED_ROUTES: dict[str, tuple[str, str]] = {
    "get_daily_attendance": ("POST", "/DailyReports/GetDailyAttendance"),
    "get_employee_wise_attendance": ("POST", "/MonthlyReports/GetEmployeeWiseAttendance"),
    "get_attendance_correction": ("POST", "/AttendanceCorrection/GetAttendance"),
    "get_punch_activity": ("POST", "/login/GetESSPunchActivity"),
    "get_leave_balance": ("POST", "/LeaveReports/GetBalanceLeave"),
    "get_employee_attendance_list": ("POST", "/DataMaintenance/GetAllEmployeeAttList"),
    "get_attendance_dashboard": ("POST", "/login/GetAttendanceDashboard"),
    "search_employees": ("POST", "/Employee/GetAllEmployee"),
}


def generated_tool_to_mcp(tool: GeneratedTool) -> Tool:
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in tool.parameters:
        prop: dict[str, Any] = {"type": param.get("type", "string")}
        if param.get("description"):
            prop["description"] = param["description"]
        if param.get("enum"):
            prop["enum"] = param["enum"]
        if param.get("format"):
            prop["format"] = param["format"]
        properties[param["name"]] = prop
        if param.get("required"):
            required.append(param["name"])

    return Tool(
        name=f"api_{tool.name}",
        description=f"[Swagger:{tool.tag}] {tool.description} ({tool.method} {tool.path})",
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


def _map_report_args(arguments: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "from_date": "fromDate",
        "to_date": "toDate",
        "pay_code": "payCode",
        "company_code": "companyCode",
        "department": "department",
        "dashboard_date": "dashboardDate",
        "search": "search",
    }
    mapped = {}
    for key, value in arguments.items():
        mapped[mapping.get(key, key)] = value
    return mapped


async def call_curated_tool(client: TamsClient, name: str, arguments: dict[str, Any]) -> Any:
    if name not in CURATED_ROUTES:
        raise ValueError(f"Unknown curated tool: {name}")

    _, path = CURATED_ROUTES[name]
    args = _map_report_args(dict(arguments))
    args = apply_default_dates(args)

    body_kind = "report"
    if name in {
        "get_daily_attendance",
        "get_leave_balance",
        "get_employee_attendance_list",
        "search_employees",
    }:
        body = build_report_payload(**args)
    elif name == "get_employee_wise_attendance":
        body = build_report_payload(
            monthly=True,
            all_employees=not args.get("payCode"),
            **args,
        )
    elif name == "get_attendance_correction":
        if "enrollment_code" in args:
            args["enrollmentCode"] = args.pop("enrollment_code")
        body = build_correction_payload(**args)
    elif name == "get_punch_activity":
        body = build_report_payload(**args)
        if "ssn" in args:
            body["ssn"] = args["ssn"]
    elif name == "get_attendance_dashboard":
        body = build_login_payload(dashboardDate=args.get("dashboardDate"), companyCode=args.get("companyCode"))
        body_kind = "login"
    else:
        body = build_report_payload(**args)

    return await client.post(path, json_body=body, body_kind=body_kind)


async def call_generated_tool(client: TamsClient, generated: GeneratedTool, arguments: dict[str, Any]) -> Any:
    query_params = {
        p["name"]: arguments[p["name"]]
        for p in generated.parameters
        if p["in"] == "query" and p["name"] in arguments
    }
    body_fields = {
        p["name"]: arguments[p["name"]]
        for p in generated.parameters
        if p["in"] == "body" and p["name"] in arguments
    }

    if generated.body_schema.lower() == "login":
        body = build_login_payload(**body_fields)
    elif generated.tag == "AttendanceCorrection" or generated.body_schema.endswith("Correction"):
        body = build_correction_payload(**body_fields)
    else:
        body = build_report_payload(**body_fields)

    path = generated.path
    for param in generated.parameters:
        if param["in"] == "path" and param["name"] in arguments:
            path = path.replace("{" + param["name"] + "}", str(arguments[param["name"]]))

    body_kind = "login" if generated.body_schema.lower() == "login" else "report"

    if generated.method == "GET":
        return await client.get(path, params=query_params or None)
    return await client.post(path, params=query_params or None, json_body=body, body_kind=body_kind)
