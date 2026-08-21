# Connect_API analysis (swagger.json)

Source: `Connect_API` OpenAPI 3.0.4 — 402 endpoints, 401 POST + 1 GET.

## Key findings

| Area | Detail |
|------|--------|
| API style | Almost all endpoints are **POST with JSON body** |
| Auth in spec | No `securitySchemes` — auth is via **`login` payload** in request bodies |
| Portal SSO | `attendance.emaratech.ae` uses Entra ID in browser; API uses TAMS credentials/context |
| Main tags | `login`, `DailyReports`, `MonthlyReports`, `LeaveReports`, `AttendanceCorrection`, `Employee`, `DataMaintenance` |

## Recommended MCP tools (curated)

| Tool | Endpoint | Purpose |
|------|----------|---------|
| `get_daily_attendance` | `/DailyReports/GetDailyAttendance` | Daily attendance rows |
| `get_employee_wise_attendance` | `/MonthlyReports/GetEmployeeWiseAttendance` | Monthly summary |
| `get_attendance_correction` | `/AttendanceCorrection/GetAttendance` | Corrections |
| `get_punch_activity` | `/login/GetESSPunchActivity` | Punch in/out activity |
| `get_leave_balance` | `/LeaveReports/GetBalanceLeave` | Leave balance |
| `get_employee_attendance_list` | `/DataMaintenance/GetAllEmployeeAttList` | Raw attendance list |
| `get_attendance_dashboard` | `/login/GetAttendanceDashboard` | Dashboard KPIs |
| `search_employees` | `/Employee/GetAllEmployee` | Employee lookup |

## Required `.env` values

```bash
TAMS_USERNAME=       # useR_R in login schema
TAMS_PASSWORD=
TAMS_PAYCODE=
TAMS_COMPANY_CODE=
TAMS_AUTH_COMP=
TAMS_AUTH_DEPT=
TAMS_AUTH_LOC=
TAMS_AUTH_SITE=
TAMS_USER_TYPE=ESS
```

Login flow: MCP server calls `/login/GetLoginDetails` on first API request, then sends report payloads with auth context fields (`payCode`, `companyCode`, `auth_comp`, etc.).

## Swagger-generated tools

Up to 60 read-only tools are auto-generated from tags listed in `SWAGGER_INCLUDE_TAGS`. Mutating endpoints (`Add*`, `Insert*`, `Approve*`, etc.) are excluded.

Regenerate manifest:

```bash
python scripts/generate-tools.py
tams-mcp --list-tools
```
