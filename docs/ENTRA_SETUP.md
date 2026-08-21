# Entra ID setup for TAMS MCP

The attendance portal (`attendance.emaratech.ae`) uses Entra ID SSO in the browser. The MCP server needs a **machine-readable token** for the TAMS REST API (`tams.emaratech.ae`).

## Step 1 — Register an Azure application

1. Azure Portal → **Microsoft Entra ID** → **App registrations** → **New registration**
2. Name: `TAMS Attendance MCP Agent`
3. Supported account types: single tenant (your org)
4. Redirect URI: not required for client credentials; add `http://localhost` for device-code testing

## Step 2 — Expose or request API permissions

Ask your TAMS/Azure admin which applies:

| Scenario | Permission type | Example |
|----------|-----------------|---------|
| TAMS has its own app registration | **Application** permission on TAMS API | `api://<tams-app-id>/.default` |
| TAMS accepts Microsoft Graph delegated access | **Delegated** (device code) | `User.Read` + custom TAMS scope |
| Portal session token reuse (dev only) | Manual bearer token | Copy from browser DevTools |

Set `TAMS_API_SCOPE` in `.env` to the scope your admin confirms.

## Step 3 — Create a client secret (service mode)

1. App registration → **Certificates & secrets** → **New client secret**
2. Copy value into `AZURE_CLIENT_SECRET`
3. Set `TAMS_AUTH_MODE=client_credentials`

## Step 4 — Grant admin consent

Enterprise applications → your app → **Permissions** → **Grant admin consent**.

Without admin consent, token acquisition fails with `AADSTS65001`.

## Step 5 — Map identity to employee ID

Many TAMS endpoints use `employeeid` rather than Entra `oid`. Options:

- Call `GetEmployeeDetailsAD` after login to resolve the current user
- Set `TAMS_DEFAULT_EMPLOYEE_ID` for single-user dev
- Pass `employee_id` explicitly in agent queries

## Auth mode reference

```bash
# Unattended / production agent
TAMS_AUTH_MODE=client_credentials

# Developer login via browser (MSAL device code)
TAMS_AUTH_MODE=device_code

# Temporary: token copied from authenticated portal session
TAMS_AUTH_MODE=bearer_token
TAMS_ACCESS_TOKEN=eyJ...
```

## Troubleshooting

| Error | Likely cause |
|-------|----------------|
| `Could not resolve host: tams.emaratech.ae` | VPN / corporate DNS required |
| `AADSTS70011` | Invalid scope — confirm TAMS API app ID |
| `401` from TAMS API | Token valid for Entra but not authorized for TAMS |
| `404` on API path | Replace example paths after swagger export |
