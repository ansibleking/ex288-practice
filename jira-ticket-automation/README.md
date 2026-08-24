# TriageDesk (AI-driven ChatOps ticket automation)

Standalone app (separate from the network-access-review tool) that triages
free-text situation reports — pasted, typed, or uploaded as a .txt/.log
file — into Jira actions: create a new ticket, log work against a ticket
already being tracked, or resolve one. Classification is done by Claude;
whether an action actually fires against Jira is decided by deterministic,
configurable confidence/severity thresholds in code — the LLM never decides
its own autonomy. Every decision (created, updated, resolved, skipped, or
proposed-and-cancelled) is written to a local audit trail independent of
Jira.

See `/home/mayil/.claude/plans/peaceful-knitting-fox.md` for the full design.

## How it decides

1. Fetches open tickets this app previously created (tagged with
   `JIRA_MANAGED_LABEL`, default `aiops-managed`) as matching candidates.
2. Sends the feed text + candidates to Claude (`client.messages.parse`,
   structured output) to classify: `new_issue` / `update_existing` /
   `resolved` / `noise`, with a confidence score, severity, and — for
   resolutions — a drafted resolution comment.
3. A pure function (`app/routing.py`) compares confidence/severity against
   `AUTONOMY_*` thresholds to decide: auto-execute, or propose and wait for
   you to confirm in the UI. High/critical severity always requires
   confirmation, regardless of confidence.
4. Resolution actions run all three sub-steps independently (comment →
   worklog → transition) so a failure in one doesn't hide that the earlier
   ones succeeded — each outcome is visible in the audit trail.

## Configuration

Copy `.env.example` to `.env` and fill in `JIRA_BASE_URL`, `JIRA_PAT`,
`JIRA_PROJECT_KEY`. The `AUTONOMY_*` thresholds
(`AUTONOMY_AUTO_CONFIDENCE_MIN=0.85`, `AUTONOMY_AUTO_SEVERITY_MAX=medium`,
`AUTONOMY_UPDATE_CONFIDENCE_MIN=0.7`) are starting guesses — tune them once
you've seen how real classifications land; nothing about them is validated
against real usage yet.

### LLM provider

`DEFAULT_LLM_PROVIDER` selects which model classifies feed text —
`anthropic` (Claude, via the Anthropic Messages API) or `onprem` (any
self-hosted model behind an OpenAI-compatible `/v1/chat/completions`
endpoint, e.g. vLLM). `DEFAULT_LLM_MODEL` is interpreted by whichever
provider is active — an Anthropic model id like `claude-opus-5`, or an
on-prem model id like `qwen/qwen3.5-122b-a10b`.

- `anthropic`: set `ANTHROPIC_API_KEY`.
- `onprem`: set `ONPREM_LLM_BASE_URL` (e.g.
  `http://onprem-llm.internal:8000/v1`) and `ONPREM_LLM_API_KEY`. The
  endpoint must support `response_format: {"type": "json_schema", ...}`
  guided decoding — vLLM's OpenAI-compatible server does — since the
  classifier relies on schema-constrained JSON output, not free-text
  parsing.

Both providers implement the same `StructuredLLMClient.parse()` interface
(`app/llm/`), so `app/classifier.py` and everything downstream of it is
provider-agnostic — routing, action execution, and the audit trail behave
identically regardless of which model classified the feed text.

## Running with Docker (recommended)

```
docker compose up --build
```

Serves the app at http://localhost:8090.

## Local development

Backend (from `backend/`):

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest
```

Frontend (from `frontend/`, requires Node 20+; not verified on this machine
since Node isn't installed here — verified instead via the Docker build):

```
npm install
npm run dev   # proxies /api to the backend dev server on :8000
```

## What's been verified so far

- Backend: 76+ pytest tests — attachment-free Jira client (search/create/
  comment/worklog/transitions, all mocked via respx), both LLM provider
  clients (`AnthropicStructuredClient`, `OnPremStructuredClient` — the
  latter respx-mocked against the vLLM/OpenAI-compatible request shape),
  the classification schema and defensive re-validation of the LLM's
  ticket-matching (mocked — no real API access in this environment), deterministic
  routing with exhaustive boundary-value tests at every threshold for every
  intent, the Jira action dispatch layer (including partial-failure
  handling in the resolve sequence), the SQLite audit store, the
  orchestration layer tying it together, and the FastAPI routes — all
  passing.
- Frontend: compiles and builds cleanly (`tsc -b && vite build`) inside the
  Docker build stage — no type errors.
- Full Docker image: builds end-to-end; container smoke-tested — frontend
  serves, `/api/health` degrades gracefully when Jira is unreachable rather
  than crashing, `/api/audit` and other routes respond correctly.

## Not yet verified

- **Behavior against real Jira and the configured LLM.** No credentials
  were available in this environment — the classifier, Jira client, and
  the full feed → classify → route → act pipeline have only been
  exercised against mocks. Point `.env` at your real (ideally test)
  project and PAT, and a real `ANTHROPIC_API_KEY` or
  `ONPREM_LLM_BASE_URL`/`ONPREM_LLM_API_KEY`, then run a handful of feed
  examples through the UI (a clear new incident, an update to something
  you've already let it create, a resolution signal, and something meant
  to read as noise) before trusting it with real tickets.
- **Whether the on-prem endpoint's guided JSON decoding actually matches
  the `FeedClassification` schema `client.post`s over.** This has only
  been exercised against a mocked response shaped the way vLLM's
  OpenAI-compatible server is documented to respond — not against a real
  vLLM instance serving `qwen/qwen3.5-122b-a10b`. If the deployed vLLM
  version or config doesn't support `response_format: json_schema`,
  `OnPremStructuredClient` will raise `OnPremLLMError` rather than
  silently misclassifying — worth a first real call before relying on it.
- **Whether the default autonomy thresholds are right for your team.**
  They're explicitly starting guesses (see Configuration above) — watch
  the audit history for a while and adjust `AUTONOMY_*` in `.env` based on
  what you see get auto-executed vs. proposed.
- The rendered UI has not been visually reviewed in a browser (no browser
  available in this environment) — worth a once-over after
  `docker compose up`.
- If this Jira DC instance requires anything beyond plain Bearer PAT auth
  for `/rest/api/2/*` calls (unlikely, since search/comment/transition are
  confirmed working that way on the sibling project's instance, and this
  app never touches attachments), `create_issue`/`add_worklog` specifically
  haven't been exercised against the real instance yet.
