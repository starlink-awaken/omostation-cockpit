# Read the project observatory

Use this guide when a task requires current project orientation, an object's upstream/downstream references, known gaps, or a bounded reading brief from the local Dashboard. It is interface guidance, not a replacement for Workspace `docs/SYSTEM-INDEX.md`, accepted Spec, Role or Workflow rules.

## Reading sequence

1. Read `/api/v1/manifest` and `/api/v1/summary`. Keep the returned generation, source ages, coverage and disabled-control boundary. If `data.reference_cell.status=R0_CANARY`, also retain its `ledger_bound=false`, `value_indicator_policy=false`, receipt schema and replay delta; it is a bounded canary, not formal completion. For `data.environment_evidence`, keep `result`, `full_gate_state`, `proven`, `missing` and evidence-age freshness together; `PARTIAL` never means gate PASS. Finish when you can state what is observed and what is not covered; do not equate installed/registered with admitted.
2. Search the exact target ID first. Use kind/provider/owner metadata only as search cues. Finish when one unique object is identified, or report AMBIGUOUS/not observed rather than choosing a convenient match.
3. Read `entity?id=...&generation=...`, then bounded `neighbors`. Keep relation_basis and gaps, including uncertain same-source-file associations. Finish when direct dependencies and unresolved references are explicitly listed; graph adjacency is not a complete impact proof.
4. Request a `brief` with a fitting lens and byte budget. Check `required_missing`, `applicable_gaps`, `omissions`, `unknowns`, `stop_conditions` and source digest scopes. Finish when each required missing item has an authorized next read or is explicitly unresolved. The brief always says `is_context_pack=false` and `sufficient_for_write=false`.
5. For a registered original document, use `/api/v1/document` with exact generation/full SHA-256 and a bounded line range. On409, reread discovery/source identity rather than joining old and new text. For other source paths, use an already-authorized canonical reader; the Dashboard does not grant a filesystem or network scope expansion.
6. Report with evidence labels: source declaration, observed/proof record, freshness, source path/hash/scope, applicable gaps and the next legal action. A source numeric observation is not independent value adjudication. Missing/old is not0/PASS.

## Stop before effects

The interface cannot authenticate your Role, acknowledge a ContextPack, acquire a claim or grant a mandate. Before any write, effect, dispatch, takeover, acceptance or closeout, return to the canonical OMO/Workspace workflow and satisfy its actual gates. A successful reading session is not evidence that those gates passed.

If a required governing source, digest, identity, binding or authority is missing/conflicting/stale, state the specific missing evidence and stop that effectful path. Continue safe in-scope reads when useful. Do not invent a formal BET, source link, owner assignment, successful window or completion receipt.

## Failure branches

- Wrong generation/cursor: rediscover and consciously choose the new snapshot; never splice pages from different generations.
- Source drift: keep both the expected version and the failure; ask the canonical owner workflow to reconcile it.
- Output budget: narrow optional related material; keep the obligations and omitted-items count. Token count is unmeasured, not bytes/4.
- Missing native tool logs or provider inventories: report the adapter coverage gap; do not initialize that tool to fill a read-only view.
- Role lens: a display aid only. `operator` or `Principal` text does not elevate access.

## Small CLI example

```sh
/opt/homebrew/bin/python3 -B /Users/xiamingxing/.local/share/zhixing-dashboard/observatory_query.py manifest
/opt/homebrew/bin/python3 -B /Users/xiamingxing/.local/share/zhixing-dashboard/observatory_query.py search --q 'BET-Y1Q3-T1-12' --kind bet --limit 5
/opt/homebrew/bin/python3 -B /Users/xiamingxing/.local/share/zhixing-dashboard/observatory_query.py search --q 'direct-local-r0' --kind reference_cell_canary --limit 5
/opt/homebrew/bin/python3 -B /Users/xiamingxing/.local/share/zhixing-dashboard/observatory_query.py search --q 'a1-managed-clone' --kind gate_evidence --limit 5
```

Take the exact ID and generation from those outputs for subsequent entity/brief requests. See `API.md` for parameter and error contracts. Avoid downloading the complete multi-megabyte site JSON as the default startup context.
