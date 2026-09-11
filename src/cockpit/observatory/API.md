# Project observer read API

This is the local Dashboard's observer transport, not an OMO execution API or an L4ContextPack compiler. The implementation in `observatory_query.py` owns query semantics; `GET /api/v1/manifest` describes the running version.

## Start small

```sh
curl --fail --silent 'http://127.0.0.1:43191/api/v1/manifest'
curl --fail --silent 'http://127.0.0.1:43191/api/v1/summary'
/opt/homebrew/bin/python3 -B /Users/xiamingxing/.local/share/zhixing-dashboard/observatory_query.py search --q 'BET-Y1Q3-T1-12' --kind bet --limit 5
```

The CLI supports the same projection operations as the HTTP query module. Pinned original-document reads use the HTTP document operation; the CLI does not accept arbitrary source-file arguments.

## Operations

All operations are GET-only under `/api/v1/`. Query parameters are single-valued. Unknown/duplicated fields are rejected. The optional `generation` parameter pins a projection query; use the generation returned by discovery/summary when joining reads. Pinned documents require it.

| Operation | Parameters | Purpose |
|---|---|---|
| manifest | generation | Operations, kinds, budgets, owner and boundaries |
| summary | generation | Known counts, at most3 attention items, source states and coverage |
| search | q, kind, limit, cursor, generation | Projected metadata, including ID/title/source/provider/owner; not full-text or semantic recall |
| entity | id, generation | One unique projection object and applicable/source-associated gaps |
| neighbors | id, direction=in/out/both, depth=1/2, limit, generation | Bounded graph edges and unresolved references; not complete business impact |
| brief | id, lens, budget_bytes, generation | Observer reading material, mandatory pointers, omissions and stop conditions |
| controls | generation | Canonical owner, prerequisites and unconnected/disabled operation boundaries |
| changes | from_generation, generation | Semantic and source-version differences between retained observations |
| document | id, generation, expected_sha256, start_line, max_lines, hash_scope | Registered document, full SHA-256 equality, then bounded original lines |

`summary.data.reference_cell` is the latest explicitly registered, digest-bound
Direct Local canary observation. Search kind `reference_cell_canary` to inspect
the same record through the common entity reader. `R0_CANARY` proves only the
recorded attempt-local Planner → Executor → Verifier and OMO Mesh receipt chain;
`ledger_bound=false` and `value_indicator_policy=false` mean it is neither a
formal BET completion nor personal-value evidence.

The enclosing entity/source freshness measures when the digest-bound registry
was last read. `facts.freshness` measures the age of the canary execution under
its registered TTL. A fresh source can therefore contain a historical canary;
these states must not be collapsed.

`summary.data.environment_evidence` contains digest-bound A1–A9 partial/full
evidence projections. Search kind `gate_evidence` for a single record. A
`PARTIAL` record always keeps `full_gate_state=NOT_PROVEN` and a non-empty
`missing` list; it may refine a gate's observed progress but cannot turn it into
PASS. Source-read freshness and evidence-age freshness remain separate.

`document` requires `id`, `generation` and a 64-hex `expected_sha256`. Only `hash_scope=full_file` is supported. Defaults: start_line1, max_lines80; max_lines≤200. A prefix hash is not a substitute for a document hash. Only registered IDs inside the library's existing document root are readable. Every directory/file hop rejects symlinks; nonregular, oversized and non-UTF8 documents are rejected. Drift returns no original text.

The old `/document?id=...` remains text/plain with `X-Observer-Read-Mode: legacy-unpinned`. It is compatibility navigation, not same-generation proof. New Agent exact-version examples must use `/api/v1/document`.

## Envelope, identity and evidence

Responses contain `schema_version=observer-query/v1`, `generation_id`, `snapshot_digest`, `generated_at`, `served_at`, `state`, `freshness`, `read_only`, `authorization_mode`, `role_is_authority`, `instruction_capable`, `data` and `response_digest`.

- `generation_id` is a publication identifier, not a content hash.
- `snapshot_digest` is SHA-256 of the snapshot's canonical JSON content.
- `response_digest` is SHA-256 of the response object excluding `response_digest`, serialized with Python `json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)`, UTF-8. This is the v1 checksum encoding, not a digital signature or a claim of RFC8785 conformance. Other-language consumers must match this encoding before comparing; source full-file SHA-256 remains the primary content check.
- `declared_status`, `observed_status`/`proof_state`, and `freshness` are separate. Source `proven` is not proof; `SOURCE_NUMERIC_OBSERVATION` describes a source record and does not mean this API independently reverified it or granted execution authority.
- Source digests retain `hash_scope` / `sha256_scope` / `digest_basis`. A `prefix:N` scope covers only those header bytes.
- Graph relationship bases remain explicit_field, explicit_receipt, filename_inferred or advisory_plan. Equal names are not enough to establish a binding.
- Gaps can be bound by exact ID/raw ID or merely the same source file. The latter is labeled `same_source_file_not_entity_binding`.

## Limits and time

Discovery lists metadata operations in `operations`; the original-text exception is advertised separately in `pinned_document`. This separation does not hide the document route. `/health` attests both deployed module hashes; generation is a publication identity, not a software revision. The three local documentation pointers are navigation aids, not generation-sealed contracts.

For document pagination, `complete=true` means this **single response** contains the entire file. A final continuation page can therefore have `complete=false` even when `end_line=total_lines`; the caller decides coverage from start/end/total for pages with the same generation and full SHA. Never splice changed versions.

`required_missing` covers the two shared navigation pointers checked by this observer, not the complete set of role/Spec/WorkPacket/claim obligations. An empty array does not grant authority or imply proof completeness. Some legacy gate `source.path` values are descriptive collector labels without a canonical record pointer or full digest; report them as non-replayable observations. Phase membership is currently also available in summary `phase_plans`; not all such memberships are graph edges.

- Snapshot input≤8MiB; output JSON≤128KiB.
- Search limit default20, range1–50. Cursor binds generation, query, limit and sorting. An expired cursor does not silently continue in another generation.
- Neighbors depth1–2, max100 objects; edges and unresolved refs are separately bounded and report truncation.
- Brief budget default16KiB, range4–64KiB, includes the complete encoded response. `used_bytes` equals actual compact JSON wire bytes. CLI and brief downloads preserve that compact encoding. Pretty display is for humans and is not the budgeted wire representation.
- No tokenizer is assumed: token count is `UNMEASURED` until an applicable provider tokenizer is selected.
- 600seconds is an observer-view staleness threshold, not a business SLO. Invalid times become null/UNKNOWN; they are never echoed as arbitrary objects. Freshness does not overwrite an evidence verdict.
- The existing collector publishes on its existing planned5-minute heartbeat. API reads do not start collection. Sleep/busy scheduling can delay publication, so actual ages remain visible.
- Only current and immediately previous valid full snapshots are retained for entity differences. Missing history returns `RESET_REQUIRED`. `no_longer_observed` is not business deletion. Semantic and source-version changes are distinguished; observation-only clock updates are not a new achievement.

## Authority and privacy

`authorization_mode=single-user-loopback` means a shared local observation surface, not per-Agent authentication. `lens` is one of overview/planner/executor/reviewer/operator; v1 labels reading intent but uses the same bounded material selection (`lens_mode=reading_label_only_same_material_selection`). It never grants Principal privileges. All effective controls are disabled in the UI and absent from the GET-only server.

Metadata queries read the published allowlisted projection. They do not execute source instructions, access arbitrary paths/URLs, call BOS/MCP, run refresh, record knowledge actions, recover databases, write Ledger/Role/Memory or dispatch workers. Metadata excludes private memory bodies, prompts and raw native tool payloads, with best-effort secret-pattern redaction (not a general DLP guarantee). The explicit `document` read is different: it returns original registered document lines after full-hash validation; those lines are not redacted and retain the source's confidentiality. Use only within the existing single-user local access boundary. Retrieved data is `instruction_capable=false`; canonical governing sources must be reread through the caller's authorized workflow before effects.

## Failure handling

| HTTP | Example code | Next read action |
|---|---|---|
| 400 | INVALID_QUERY, INVALID_CURSOR, PINNED_DOCUMENT_PARAMETERS_REQUIRED | Correct the bounded request; do not invent missing digest/identity |
| 403 | same_origin_required, document_path_denied | Respect scope; do not retry via arbitrary path or relaxed proxy |
| 404 | ENTITY_NOT_OBSERVED, DOCUMENT_NOT_REGISTERED | Inspect coverage; absence from this projection is not global absence |
| 409 | GENERATION_EXPIRED, AMBIGUOUS, RESET_REQUIRED, DOCUMENT_SOURCE_DRIFT | Rediscover/review exact identity or source; do not join mixed generations |
| 413 | RESPONSE_BUDGET_EXCEEDED, REQUIRED_CONTEXT_EXCEEDS_BUDGET | Narrow the requested data; preserve missing obligations |
| 503 | SNAPSHOT_UNAVAILABLE, TRACE_SCHEMA_UNAVAILABLE | Retain known old evidence as stale/unavailable, not empty success |
| 405 | read_only_get_only | Use the canonical OMO workflow for effectful work, not this server |

Host/Origin checks prevent accidental browser cross-origin exposure but do not authenticate local Agent identities. A remote deployment or true per-role access policy requires its own governed security design.
