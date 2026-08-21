# TAMS API authentication (401 fix)

Claude works. **401 from TAMS** = Connect_API auth is not accepted.

## Step 1 — Test TAMS directly (after rebuild)

```bash
sudo docker-compose build --no-cache
sudo docker-compose run --rm mcp -- --check-tams
```

You want:

```
Login step: OK (tams_login, cookies=1)
Report call: OK (cookies=1)
```

If login OK but report **400 Bad Request** → payload issue (fixed in latest code: report bodies no longer include login-only fields like `password`; dates use `dd/MM/yyyy`).

---

## Option A — TAMS username/password in `.env`

```bash
TAMS_BASE_URL=https://tams.emaratech.ae
TAMS_AUTH_MODE=tams_login

TAMS_USERNAME=your_username
TAMS_PASSWORD=your_password
TAMS_PAYCODE=your_pay_code
TAMS_COMPANY_CODE=your_company_code
TAMS_AUTH_COMP=*
TAMS_AUTH_DEPT=*
TAMS_AUTH_LOC=*
TAMS_AUTH_SITE=*
TAMS_USER_TYPE=ESS
```

Get `TAMS_AUTH_*` values from your TAMS admin (same scope as your portal user). After login, the MCP server also reads `auth_comp`, `auth_dept`, `auth_location`, and `auth_site` from the `GetLoginDetails` response when present.

---

## Option B — Bearer token from browser (Entra SSO)

1. Log in to https://attendance.emaratech.ae
2. DevTools → Network → pick any API call to `tams.emaratech.ae`
3. Copy the `Authorization: Bearer eyJ...` value

```bash
TAMS_AUTH_MODE=bearer_token
TAMS_ACCESS_TOKEN=eyJ...paste-without-Bearer-prefix...
```

---

## Option C — Session cookie from browser

1. Log in to the attendance portal
2. DevTools → Application → Cookies → copy the session cookie(s)
3. Format as `name=value; name2=value2`

```bash
TAMS_SESSION_COOKIE=.AspNetCore.Session=abc123; other=cookie
```

You can combine Option B + A if needed.

---

## Step 2 — Run the agent

```bash
LLM_PROFILE=claude-sonnet sudo docker-compose --profile agent run --rm agent -- "Get employee wise attendance for this month"
```

---

## What we fixed in code

- **Persistent HTTP session** — login cookies are kept between `GetLoginDetails` and report calls
- **Login fields embedded** in every POST body (Connect_API requirement)
- **`--check-tams`** — tests login + report before using the agent
