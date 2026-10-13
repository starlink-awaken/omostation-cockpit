---
type: ssot
last_updated: 2026-09-04
last-reviewed: 2026-08-26
owner: governance-team
---

# Cockpit API / Usage Reference

> Quick reference for using **Cockpit** programmatically and from the command line.

## Command Line

- `uv run python -m cockpit` — CLI
- `uv run python src/cockpit/dashboard_server.py` — dashboard

## Programmatic API

Import `cockpit.cli` or use the MCP server for programmatic access.

### Engineering-delivery shadow review

- `GET /api/workflow-mesh/engineering-delivery/review-queue` requires a configured API key with `read` or `engineering-review` scope.
- `POST /api/workflow-mesh/engineering-delivery/review` requires the explicit `engineering-review` scope; the generic `admin` scope is intentionally insufficient.
- The POST body accepts only `workflow_run_id`, `delivery_id`, `decision`, and `evidence_refs`. Cockpit derives the reviewer identity and review time; clients must not send `actor_ref` or `reviewed_at`.
- Configure a 32+ character `COCKPIT_ENGINEERING_REVIEW_SIGNING_KEY` with the same value in Cockpit and OMO. This signs the normalized workflow, candidate receipt, and review binding; it does not change the scene's `shadow` tier or its `value_indicator_policy=false` isolation.

Use `X-Api-Key` or `Authorization: Bearer` with a credential declared in `config/api_keys.yaml`; see `config/api_keys.yaml.example`.

```bash
curl -H "X-Api-Key: ${COCKPIT_REVIEW_API_KEY}" \
  "http://127.0.0.1:8090/api/workflow-mesh/engineering-delivery/review-queue"

curl -X POST -H "X-Api-Key: ${COCKPIT_REVIEW_API_KEY}" \
  -H "Content-Type: application/json" \
  --data '{"workflow_run_id":"<run-id>","delivery_id":"<receipt-id>","decision":"adopted","evidence_refs":["evidence://human-review/<id>"]}' \
  "http://127.0.0.1:8090/api/workflow-mesh/engineering-delivery/review"
```

### Personal episode confirmation

Personal episode confirmation is protected by a dedicated credential. The
credential must have the `personal-confirmation` scope and a server-side
`principal_id` binding in `config/api_keys.yaml`; the `principal_id` submitted
in the request body is checked against that binding. Use a real configured
principal identity; fixture identities such as `principal:alice` are rejected
on the production path. This remains strict even when
`COCKPIT_AUTH_REQUIRED=false`.

The protected effectful endpoints are:

- `POST /api/workflow-mesh/personal-episode/confirm`
- `POST /api/workflow-mesh/personal-episode/execute`
- `POST /api/workflow-mesh/personal-episode/feedback`

Send the credential with `X-Api-Key` (or `Authorization: Bearer`). Do not put a
real key in source control, shell history, examples, or request bodies. A
complete key entry is shown in [`../config/api_keys.yaml.example`](../config/api_keys.yaml.example).

The personal dogfood CLI reads the following environment variables:

| Variable | Required | Purpose |
|:---------|:---------|:--------|
| `COCKPIT_PERSONAL_CONFIRMATION_API_KEY` | For confirm/execute/feedback | API key with the `personal-confirmation` scope |
| `COCKPIT_PERSONAL_CONFIRMATION_PRINCIPAL_ID` | Optional | Default principal for personal CLI commands; it must match the key's server-side binding |
| `COCKPIT_API_URL` | Optional | Cockpit API base URL; defaults to `http://127.0.0.1:8090` |

For example, with a key configured for `principal:your-production-identity`:

```bash
export COCKPIT_PERSONAL_CONFIRMATION_API_KEY='replace-with-your-personal-confirmation-key'
export COCKPIT_PERSONAL_CONFIRMATION_PRINCIPAL_ID='principal:your-production-identity'

uv run cockpit workflow mesh personal confirm --episode-id '<episode-id>'
uv run cockpit workflow mesh personal draft --episode-id '<episode-id>'
uv run cockpit workflow mesh personal feedback --episode-id '<episode-id>' --verdict accept
```

The CLI sends `COCKPIT_PERSONAL_CONFIRMATION_API_KEY` only to the three
effectful endpoints above. Read-only status and setup/ingest calls do not use
this credential.

## Configuration

- Stack: python
- Dependencies: see [`../pyproject.toml`](../pyproject.toml) (Python) or [`../package.json`](../package.json) (TypeScript).
- Environment variables and ports: see workspace `protocols/port-registry.yaml` and root `.env.example`.

## Tests

See [`../README.md`](../README.md) for the test command.
