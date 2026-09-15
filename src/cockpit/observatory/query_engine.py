"""Bounded observer queries over a published projection, never an execution API.

No Workspace imports, network calls, writes, or command execution. Runtime file
selection belongs to SnapshotStore; query inputs cannot select files or URLs.
"""
from __future__ import annotations

import argparse
import base64
import copy
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
FRESHNESS_SECONDS = 600
LENSES = ('overview', 'planner', 'executor', 'reviewer', 'operator')
NUMERIC_EVIDENCE = {'proven_numeric', 'verified_numeric', 'direct_numeric_proof',
                    'outcome_observation_numeric', 'human_verdict_numeric'}
OPERATIONS = {
    'manifest': set(), 'summary': set(),
    'search': {'q', 'kind', 'limit', 'cursor'}, 'entity': {'id'},
    'neighbors': {'id', 'direction', 'depth', 'limit'},
    'brief': {'id', 'lens', 'budget_bytes'}, 'controls': set(),
    'changes': {'from_generation'},
    'ontology': set(),
    'lineage': {'id', 'direction', 'depth'},
    'context_pack': {'id'}, 'scene_status': {'kind'}, 'scene_graph': {'root', 'depth'},
}
SOURCE_KEYS = {'path', 'sha256', 'hash_scope', 'sha256_scope', 'digest_basis', 'line',
               'observed_at', 'repository_sha', 'repository_ref', 'repository_kind',
               'status', 'state', 'reason', 'partial', 'document_id'}
FACT_KEYS = {
    'id', 'raw_id', 'title', 'name', 'description', 'owner', 'owner_role', 'objective',
    'status', 'state', 'ref', 'path', 'digest', 'sha256', 'version', 'kind', 'type',
    'bet_id', 'bet_refs', 'spec_id', 'spec_ref', 'spec_digest', 'work_packet_id',
    'work_packet_ref', 'work_packet_digest', 'run_id', 'actor', 'agent_id', 'profile',
    'role', 'runtime_id', 'provider', 'model', 'layer', 'stack', 'transport',
    'definition_path', 'exists', 'exists_basis', 'online', 'source_state',
    'depends_on', 'dependencies', 'source_refs', 'accepted_specifications',
    'accepted_specification', 'accepted_spec_ref', 'accepted_spec_digest',
    'completion_matrix', 'completion_evidence', 'engineering', 'operational', 'value',
    'overall', 'current', 'baseline', 'target', 'unit', 'operator', 'numerator',
    'denominator', 'dimension', 'category', 'exclusions', 'verdict', 'evidence_class',
    'missing_reason', 'normalization', 'score', 'reason', 'window', 'metric_version',
    'approval_state', 'authority_class', 'authority_scope', 'implementation_authorized',
    'relation_basis', 'source_key', 'section', 'section_ref', 'line', 'document_id',
    'document_type', 'parent_ref', 'objective_id', 'campaign_id', 'milestone_id',
    'strategy_ref', 'horizon_end', 'next_action', 'next', 'severity', 'acceptance',
    'forbidden', 'prohibited', 'upstream_refs', 'formal_bet_id', 'candidate_key',
    'write_surfaces', 'read_surfaces', 'effect_surfaces', 'rollback_ref', 'policy_refs',
    'claims', 'claim_refs', 'lease_ref', 'lease_expires_at', 'expires_at', 'created_at',
    'updated_at', 'closed_at', 'completed_at', 'roles', 'phase_ids', 'run_frequency',
    'primary', 'secondary', 'sensor', 'controller', 'actuator', 'feedback', 'delay',
    'brake', 'proof_state', 'declared_id', 'variables', 'links', 'boundaries',
    'read_policy', 'data_policy', 'review_due', 'last-reviewed', 'status_basis',
    'exit', 'exit_gate', 'gate_members', 'writer_limit', 'candidate_bets',
    'uri', 'domain', 'service', 'operation', 'read_only', 'declared_status', 'lifecycle_state', 'bet_ref', 'evidence_refs',
    'band', 'label', 'ref_panel',
    'owner_basis', 'assigned_agent', 'gap_kind', 'related_entity_ids', 'readiness',
    'cell', 'execution', 'verification', 'mesh', 'summary_sha256', 'ledger_bound',
    'value_indicator_policy', 'external_side_effects', 'workspace_writes', 'clone_root_sha',
    'handoff_count', 'event_count', 'receipt_event_id', 'receipt_schema', 'replay_status',
    'replay_event_count_delta', 'result_digest', 'risk', 'backend', 'completed', 'action',
    'qualification', 'qualification_state', 'freshness', 'age_seconds', 'ttl_seconds',
    'scope', 'observed_at', 'gate_id', 'result', 'full_gate_state', 'proven', 'missing',
    'default_gate', 'clone', 'checks', 'returncode', 'assertion', 'stdout_sha256',
    'stderr_sha256', 'stdout_bytes', 'stderr_bytes', 'root_sha', 'manifest_digest',
    'branch', 'actor_id', 'delivery_attempt_id', 'root_clean', 'top_level_submodules_verified',
    # Scene system (panorama extensions, Serena Phase D)
    'watermark_entries', 'scenes_with_triggers', 'last_poll', 'state_keys', 'available_connectors',
    'total', 'with_trigger', 'note', 'lifecycle', 'stage', 'count',
    'escalated', 'succeeded', 'failed', 'auto_complete_rate', 'top_escalated',
    'origin_canonical', 'origin_push_canonical', 'last_fix_remotes_run', 'submodules_checked',
    'services', 'available', 'wired_to_scenes', 'unwired_available',
    'last_run_ok', 'last_run_errors', 'output_tail',
}
TIME_KEYS = {'observed_at', 'generated_at', 'created_at', 'updated_at', 'closed_at', 'completed_at',
             'expires_at', 'lease_expires_at', 'last_success_at', 'last_attempt_at'}
SCALAR_TEXT_KEYS = {'id', 'raw_id', 'title', 'name', 'description', 'objective', 'owner', 'owner_role',
                     'kind', 'type', 'status', 'state', 'path', 'uri', 'reason', 'missing_reason', 'verdict',
                     'declared_status', 'lifecycle_state', 'evidence_class', 'role', 'provider', 'profile',
                     'approval_state', 'authority_class', 'authority_scope', 'summary',
                     'last_poll', 'watermark_entries', 'scenes_with_triggers', 'auto_complete_rate'}
SECRET = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|sk-[A-Za-z0-9_-]{16,})\b')
ASSIGNMENT_SECRET = re.compile(r'(?i)(bearer\s+|(?:password|secret|token|api[-_]?key)\s*[:=]\s*)[^\s,;]+')


class QueryError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def content_digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def without_sampling_time(value):
    """Observation clocks are not business changes; preserve real lifecycle times."""
    if isinstance(value, dict):
        return {key: without_sampling_time(item) for key, item in value.items()
                if key not in {'observed_at', 'generated_at', 'last_attempt_at', 'last_observed_at', 'last_success_at'}}
    if isinstance(value, list):
        return [without_sampling_time(item) for item in value]
    return value


def text(value):
    if not isinstance(value, (str, int, float, bool)):
        return ''
    cleaned = re.sub(r'[\x00-\x1f]', ' ', str(value))
    cleaned = re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[REDACTED]@', cleaned)
    return ASSIGNMENT_SECRET.sub(r'\1[REDACTED]', SECRET.sub('[REDACTED]', cleaned))


def mapping(value):
    return value if isinstance(value, dict) else {}


def rows(value):
    return value if isinstance(value, list) else []


def project(value, allowed, depth=0):
    if depth > 8:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or key not in allowed:
                continue
            if key in TIME_KEYS:
                result[key] = safe_timestamp(item)
            elif key in SCALAR_TEXT_KEYS:
                result[key] = text(item) or None
            elif key == 'source':
                result[key] = source_of(item)
            elif key == 'source_refs':
                result[key] = [source_of(ref) if isinstance(ref, dict) else text(ref) for ref in rows(item)]
            else:
                result[key] = project(item, allowed, depth + 1)
        return result
    if isinstance(value, list):
        return [project(item, allowed, depth + 1) for item in value]
    if isinstance(value, str):
        return text(value)
    if value is None or isinstance(value, (int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def source_of(value):
    if isinstance(value, str):
        return {'path': text(value)}
    result = {}
    for key, item in mapping(value).items():
        if key not in SOURCE_KEYS:
            continue
        if key in TIME_KEYS:
            result[key] = safe_timestamp(item)
        elif key == 'line':
            result[key] = item if type(item) is int and item > 0 else None
        elif key == 'partial':
            result[key] = item if type(item) is bool else None
        else:
            result[key] = text(item) or None
    return result


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def freshness(observed, stamp):
    observed = safe_timestamp(observed)
    when, now = parse_time(observed), parse_time(stamp)
    if when is None or now is None:
        return {'state': 'UNKNOWN', 'observed_at': observed, 'age_seconds': None,
                'ttl_seconds': FRESHNESS_SECONDS, 'scope': 'observer_view_not_business_slo'}
    age = int((now - when).total_seconds())
    state = 'CLOCK_SKEW' if age < -60 else 'STALE' if age > FRESHNESS_SECONDS else 'FRESH'
    return {'state': state, 'observed_at': observed, 'age_seconds': age,
            'ttl_seconds': FRESHNESS_SECONDS, 'scope': 'observer_view_not_business_slo'}


def safe_timestamp(value):
    parsed = parse_time(value)
    return parsed.isoformat().replace('+00:00', 'Z') if parsed is not None else None


def proof_reference(ref):
    if not isinstance(ref, dict):
        return False
    path, sha = ref.get('path'), ref.get('sha256')
    scope = ref.get('hash_scope') or ref.get('sha256_scope') or ref.get('digest_basis')
    return (isinstance(path, str) and bool(re.match(r'^(?:(?:repo|github|evidence|receipt|decision|bos|mof)://|(?:workspace|library):|(?:docs|tests|\.omo)/)', path))
            and isinstance(sha, str) and bool(re.fullmatch(r'[a-fA-F0-9]{64}', sha))
            and scope in ('full_file', 'canonical_json_content', 'content_hash_and_heading_index'))


def integer(params, key, default, minimum, maximum):
    value = params.get(key, str(default))
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}', value):
        raise QueryError(400, 'INVALID_' + key.upper())
    result = int(value)
    if not minimum <= result <= maximum:
        raise QueryError(400, 'INVALID_' + key.upper())
    return result


def stable_id(kind, raw):
    return kind + ':' + text(raw)


class ObservationIndex:
    def __init__(self, snapshot, snapshot_digest=None, observed_now=None):
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('generation_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', snapshot['generation_id'])):
            raise QueryError(503, 'SNAPSHOT_SCHEMA_UNAVAILABLE')
        strategy = snapshot.get('strategic')
        if not isinstance(strategy, dict) or not isinstance(strategy.get('trace'), dict):
            raise QueryError(503, 'STRATEGY_PROJECTION_UNAVAILABLE')
        if any(not isinstance(strategy['trace'].get(key), list) for key in ('nodes', 'edges')):
            raise QueryError(503, 'TRACE_SCHEMA_UNAVAILABLE')
        self.generation = snapshot['generation_id']
        self.generated_at = safe_timestamp(snapshot.get('generated_at'))
        try:
            self.snapshot_digest = snapshot_digest or content_digest(snapshot)
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise QueryError(503, 'SNAPSHOT_SCHEMA_UNAVAILABLE') from None
        self.observed_now = safe_timestamp(observed_now)
        self.state = text(strategy.get('state') or 'UNKNOWN')
        self.previous = None
        self.entities = {}
        self.duplicates = set()
        self.edges = []
        self.adjacency = defaultdict(list)
        self.sources = {key: project(item, {'status', 'last_success_at', 'last_attempt_at', 'last_observed_at', 'reason'})
                        for key, item in mapping(snapshot.get('source_states')).items() if isinstance(item, dict)}
        self.gaps = project(rows(mapping(strategy.get('trace')).get('gaps')),
                            FACT_KEYS | {'entity_id', 'source'})
        self.phase_plans = project(rows(strategy.get('phase_plans')), FACT_KEYS)
        self.scope = copy.deepcopy(mapping(mapping(strategy.get('trace')).get('scope')))
        self.trace = copy.deepcopy(mapping(strategy.get('trace')))
        self.axioms = copy.deepcopy(mapping(strategy.get('axioms')))
        self.history_coverage = project(mapping(mapping(strategy.get('reports')).get('history')).get('coverage'),
                                        {'sampled_hours', 'sampled_days', 'retention_days', 'method', 'value_window_proven'})
        for node in rows(strategy['trace'].get('nodes')):
            if not isinstance(node, dict) or not isinstance(node.get('id'), str):
                continue
            self._add(node['id'], node.get('kind', 'unknown'), node.get('title', node['id']),
                      node.get('status'), node.get('source'), node.get('facts'),
                      node.get('evidence_class'), node.get('observed_at'))
        for edge in rows(strategy['trace'].get('edges')):
            self._edge(edge)
        catalog = mapping(snapshot.get('catalog'))
        catalog_sources = {item.get('path'): item for item in rows(catalog.get('sources')) if isinstance(item, dict)}
        for section, kind in [('projects', 'project'), ('capabilities', 'capability'), ('bos_services', 'bos_service')]:
            for item in rows(catalog.get(section)):
                if not isinstance(item, dict):
                    continue
                raw_id = item.get('id') or item.get('uri') or item.get('name')
                if not raw_id:
                    continue
                # Capability kinds are distinct registry namespaces.
                raw_id = str(item.get('kind', '')) + ':' + str(raw_id) if kind == 'capability' else raw_id
                src = dict(catalog_sources.get(item.get('source'), {}), path=item.get('source'))
                self._add(stable_id(kind, raw_id), kind, item.get('title') or item.get('name') or raw_id,
                          item.get('status') or 'declared', src, item, 'registry_declaration', src.get('observed_at'))
        for gate in rows(mapping(snapshot.get('runtime')).get('gates')):
            if isinstance(gate, dict) and gate.get('id'):
                self._add(stable_id('gate', gate['id']), 'gate', gate['id'], gate.get('verdict'),
                          {'path': gate.get('source'), 'observed_at': gate.get('observed_at')},
                          dict(gate, description=gate.get('summary')), 'bounded_observation', gate.get('observed_at'))
        for agent in rows(snapshot.get('live_agents')):
            if isinstance(agent, dict) and agent.get('id'):
                self._add(stable_id('agent_observation', str(agent.get('source')) + ':' + str(agent['id'])),
                          'agent_observation', agent.get('name') or agent['id'], agent.get('status'),
                          {'path': agent.get('source'), 'observed_at': agent.get('observed_at')},
                          agent, 'inventory_observation', agent.get('observed_at'))
        reference_cell = mapping(snapshot.get('reference_cell'))
        self.reference_cell = project(mapping(reference_cell.get('latest')), FACT_KEYS)
        if self.reference_cell.get('id'):
            reference_source_observed_at = safe_timestamp(reference_cell.get('observed_at'))
            reference_source = {'path': 'dashboard:reference-cell-sources.json',
                                'sha256': self.reference_cell.get('summary_sha256'),
                                'hash_scope': 'full_file',
                                'observed_at': reference_source_observed_at}
            self._add(stable_id('reference_cell_canary', self.reference_cell['id']),
                      'reference_cell_canary', 'Direct Local Reference Cell R0',
                      self.reference_cell.get('status'), reference_source, self.reference_cell,
                      'digest_bound_attempt_local_canary', reference_source_observed_at)
        environment = mapping(snapshot.get('environment_evidence'))
        self.environment_evidence = project(rows(environment.get('records')), FACT_KEYS)
        environment_source_observed_at = safe_timestamp(environment.get('observed_at'))
        for record in self.environment_evidence:
            if not isinstance(record, dict) or not record.get('id') or not record.get('gate_id'):
                continue
            source = {'path': 'dashboard:execution-environment-sources.json',
                      'sha256': record.get('summary_sha256'), 'hash_scope': 'full_file',
                      'observed_at': environment_source_observed_at}
            self._add(stable_id('gate_evidence', record['id']), 'gate_evidence',
                      record['gate_id'] + ' execution environment evidence', record.get('result'),
                      source, record, 'digest_bound_environment_evidence', environment_source_observed_at)
        for role in rows(snapshot.get('role_design')):
            if isinstance(role, list) and len(role) >= 4:
                self._add(stable_id('role_design', role[0]), 'role_design', role[0], 'design_only', {},
                          {'description': role[1], 'authority_scope': role[2], 'prohibited': role[3]}, 'advisory_plan', None)
        for metric in rows(strategy.get('metrics')):
            if isinstance(metric, dict) and metric.get('id'):
                declaration = mapping(metric.get('facts')).get('declared_status')
                self._add(stable_id('metric', metric['id']), 'metric', metric.get('title'), declaration or metric.get('verdict'),
                          {}, metric, metric.get('evidence_class'), metric.get('observed_at'))
        model = mapping(strategy.get('model'))
        source_documents = mapping(model.get('source_documents'))
        macro = mapping(model.get('macro'))
        drill = mapping(macro.get('detail_example'))
        for node in rows(macro.get('nodes')) + rows(drill.get('nodes')):
            if not isinstance(node, dict) or not node.get('id'):
                continue
            src = dict(mapping(source_documents.get(node.get('source_key'))))
            matching = [doc for doc in rows(strategy.get('documents')) if isinstance(doc, dict)
                        and doc.get('path') == src.get('path') and doc.get('sha256') == src.get('sha256')
                        and doc.get('observation_scope') == 'content_hash_and_heading_index']
            if len(matching) == 1:
                src.update(observed_at=matching[0].get('observed_at'), hash_scope='full_file')
            src['line'] = node.get('line')
            self._add(stable_id('architecture', node['id']), 'architecture_node', node.get('label') or node['id'],
                      'design_only', src, dict(node, raw_id=node['id']), 'advisory_plan', src.get('observed_at'))
        for edge in rows(macro.get('edges')) + rows(drill.get('relations')):
            if isinstance(edge, dict) and edge.get('from') and edge.get('to'):
                self._edge({'from': stable_id('architecture', edge['from']), 'to': stable_id('architecture', edge['to']),
                            'relation': edge.get('relation') or edge.get('label') or 'declared_relation',
                            'relation_basis': edge.get('relation_basis') or 'advisory_plan', 'source': edge.get('source')})
        for loop in rows(model.get('loops')):
            if isinstance(loop, dict) and loop.get('id'):
                src = mapping(source_documents.get(loop.get('source_key')))
                self._add(stable_id('loop_contract', loop['id']), 'loop_contract', loop.get('label') or loop['id'],
                          loop.get('proof_state'), src, loop, 'advisory_plan', None)
        for gap in self.gaps:
            if gap.get('id'):
                self._add(gap['id'], 'gap', gap.get('title'), 'open_observation', gap.get('source'),
                          gap, 'projection_gap', mapping(gap.get('source')).get('observed_at'))
        for conflict in rows(model.get('contradictions')):
            if isinstance(conflict, dict) and conflict.get('id'):
                refs = []
                for ref in rows(conflict.get('source_refs')):
                    if not isinstance(ref, dict):
                        continue
                    src = dict(mapping(source_documents.get(ref.get('source_key'))))
                    src['line'] = ref.get('line'); refs.append(src)
                self._add(conflict['id'], 'contract_conflict', conflict.get('title'), 'review_required',
                          refs[0] if refs else {}, dict(conflict, source_refs=refs), 'advisory_plan', None)
        for candidate in rows(strategy.get('proposals')):
            if isinstance(candidate, dict) and candidate.get('candidate_key'):
                self._add(stable_id('review', candidate['candidate_key']), 'review_candidate', candidate.get('title'),
                          candidate.get('status'), {}, candidate, 'advisory_plan', strategy.get('observed_at'))
        for source in rows(strategy.get('source_states')):
            if isinstance(source, dict) and source.get('id'):
                self._add(stable_id('source_observation', source['id']), 'source_observation', source.get('path'),
                          source.get('status'), source, source, 'source_observation', source.get('observed_at'))
        # Scene system (from panorama snapshot extensions)
        self._register_scene_system(snapshot)
        self.documents = [project(doc, {'id', 'title', 'path', 'sha256', 'observed_at', 'authority_class',
                                        'approval_state', 'authority_scope', 'document_type', 'observation_scope'})
                          for doc in rows(strategy.get('documents')) if isinstance(doc, dict)]
        self.document_registry = {'documents': copy.deepcopy(rows(snapshot.get('documents'))),
                                  'envelope': copy.deepcopy(mapping(snapshot.get('envelope')))}
        self.contradictions = project(rows(model.get('contradictions')),
                                       FACT_KEYS | {'summary', 'statements', 'statement', 'next_action'})
        self.aliases = defaultdict(set)
        for identity, entity in self.entities.items():
            raw_id = entity['facts'].get('raw_id')
            if isinstance(raw_id, str):
                self.aliases[raw_id].add(identity)
        for identity, entity in list(self.entities.items()):
            if entity['kind'] != 'review_candidate':
                continue
            refs = rows(entity['facts'].get('upstream_refs')) + rows(entity['facts'].get('related_entity_ids'))
            targets_seen = set()
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                matches = self.aliases.get(ref, set())
                target = ref if ref in self.entities else next(iter(matches)) if len(matches) == 1 else ref
                if target in targets_seen:
                    continue
                targets_seen.add(target)
                self._edge({'from': identity, 'to': target, 'relation': 'reviews',
                            'relation_basis': 'explicit_advisory_reference', 'source': entity['source']})

    def _register_scene_system(self, snapshot: dict) -> None:
        """Register panorama scene-system extensions as observable entities."""
        # Scene cards lifecycle
        sc = mapping(snapshot.get('scene_cards'))
        if sc.get('total'):
            facts = {'total': sc.get('total'), 'with_trigger': sc.get('with_trigger'),
                     'note': sc.get('note', ''), 'available_connectors':
                     sc.get('available_connectors', [])}
            self._add('scene_system:cards', 'scene_cards', 'Scene Card Lifecycle',
                      'observed', {'path': 'panorama:scene_cards', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
            lifecycle = mapping(sc.get('lifecycle'))
            if isinstance(lifecycle, dict):
                items = list(lifecycle.items())
            else:
                items = [(str(row.get('stage', row.get('name', ''))),
                          row.get('count', 0))
                         for row in rows(lifecycle) if isinstance(row, dict)]
            for stage, count in items:
                if not stage:
                    continue
                self._add('scene_system:cards:' + str(stage), 'scene_card_stage', 'Stage ' + str(stage),
                          'observed', {'path': 'panorama:scene_cards', 'observed_at': snapshot.get('generated_at')},
                          {'stage': stage, 'count': count}, 'panorama_observation', snapshot.get('generated_at'))
        # Signal poller
        sp = mapping(snapshot.get('signal_poller'))
        if sp.get('watermark_entries') is not None:
            facts = {'watermark_entries': sp.get('watermark_entries'),
                     'scenes_with_triggers': sp.get('scenes_with_triggers'),
                     'last_poll': sp.get('last_poll'),
                     'state_keys': sp.get('state_keys', []),
                     'available_connectors': sp.get('available_connectors', [])}
            self._add('scene_system:signal_poller', 'signal_poller', 'Signal Poller',
                      'observed', {'path': 'panorama:signal_poller', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # Journey executions
        je = mapping(snapshot.get('journey_executions'))
        if je.get('total'):
            facts = {'total': je.get('total'), 'escalated': je.get('escalated', 0),
                     'succeeded': je.get('succeeded', 0), 'failed': je.get('failed', 0),
                     'auto_complete_rate': je.get('auto_complete_rate', 0),
                     'top_escalated': je.get('top_escalated', [])}
            self._add('scene_system:journey_executions', 'journey_executions', 'Journey Executions',
                      'observed', {'path': 'panorama:journey_executions', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # Remote hygiene
        rh = mapping(snapshot.get('remote_hygiene'))
        if rh.get('submodules_checked') is not None:
            facts = {'origin_canonical': rh.get('origin_canonical'),
                     'origin_push_canonical': rh.get('origin_push_canonical'),
                     'last_fix_remotes_run': rh.get('last_fix_remotes_run'),
                     'submodules_checked': rh.get('submodules_checked')}
            self._add('scene_system:remote_hygiene', 'remote_hygiene', 'Remote Hygiene',
                      'observed', {'path': 'panorama:remote_hygiene', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # Service keeper
        sk = mapping(snapshot.get('service_keeper'))
        if sk.get('services'):
            facts = {'services': sk.get('services')}
            self._add('scene_system:service_keeper', 'service_keeper', 'Service Keeper',
                      'observed', {'path': 'panorama:service_keeper', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # Connectors
        co = mapping(snapshot.get('connectors'))
        if co.get('total'):
            facts = {'total': co.get('total'), 'available': co.get('available', []),
                     'wired_to_scenes': co.get('wired_to_scenes', []),
                     'unwired_available': co.get('unwired_available', [])}
            self._add('scene_system:connectors', 'connectors', 'Connectors',
                      'observed', {'path': 'panorama:connectors', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # BOS verifier
        bv = mapping(snapshot.get('bos_verifier'))
        if bv.get('last_run_ok') is not None:
            facts = {'last_run_ok': bv.get('last_run_ok'), 'last_run_errors': bv.get('last_run_errors'),
                     'output_tail': bv.get('output_tail', [])}
            self._add('scene_system:bos_verifier', 'bos_verifier', 'BOS URI Verifier',
                      'observed', {'path': 'panorama:bos_verifier', 'observed_at': snapshot.get('generated_at')},
                      facts, 'panorama_observation', snapshot.get('generated_at'))
        # Wire scene_system entities into a single chain
        self._edge({'from': 'scene_system:cards', 'to': 'scene_system:signal_poller',
                    'relation': 'monitors', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:scene_cards'}})
        self._edge({'from': 'scene_system:signal_poller', 'to': 'scene_system:journey_executions',
                    'relation': 'drives', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:signal_poller'}})
        self._edge({'from': 'scene_system:journey_executions', 'to': 'scene_system:remote_hygiene',
                    'relation': 'tracked_by', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:journey_executions'}})
        self._edge({'from': 'scene_system:remote_hygiene', 'to': 'scene_system:service_keeper',
                    'relation': 'probes', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:remote_hygiene'}})
        self._edge({'from': 'scene_system:service_keeper', 'to': 'scene_system:connectors',
                    'relation': 'discovers', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:service_keeper'}})
        self._edge({'from': 'scene_system:connectors', 'to': 'scene_system:bos_verifier',
                    'relation': 'validates', 'relation_basis': 'panorama_rollup',
                    'source': {'path': 'panorama:connectors'}})

    def _add(self, identity, kind, title, status, source, facts, evidence, observed):
        if identity in self.entities:
            self.duplicates.add(identity)
            return
        clean_facts = project(mapping(facts), FACT_KEYS)
        entity = {'id': text(identity), 'kind': text(kind), 'title': text(title or identity),
                  'declared_status': text(status or 'UNKNOWN'), 'evidence_class': text(evidence or 'unknown'),
                  'source': source_of(source), 'observed_at': safe_timestamp(observed), 'facts': clean_facts,
                  'instruction_capable': False}
        entity['content_digest'] = content_digest(without_sampling_time({k: v for k, v in entity.items() if k != 'source'}))
        entity['provenance_digest'] = content_digest({k: v for k, v in entity['source'].items() if k != 'observed_at'})
        self.entities[identity] = entity

    def _edge(self, edge):
        if not isinstance(edge, dict) or not isinstance(edge.get('from'), str) or not isinstance(edge.get('to'), str):
            return
        clean = {key: text(edge.get(key, 'UNKNOWN')) for key in ('from', 'to', 'relation', 'relation_basis')}
        clean['source'] = source_of(edge.get('source'))
        self.edges.append(clean)
        self.adjacency[clean['from']].append(clean)
        self.adjacency[clean['to']].append(clean)

    def _now(self):
        return self.observed_now or datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    def _entity(self, identity, stamp):
        if identity in self.duplicates:
            raise QueryError(409, 'AMBIGUOUS')
        if identity not in self.entities:
            raise QueryError(404, 'ENTITY_NOT_OBSERVED')
        entity = copy.deepcopy(self.entities[identity])
        observed = entity['source'].get('observed_at') or entity.get('observed_at')
        entity['freshness'] = freshness(observed, stamp)
        entity['proof_state'] = 'UNPROVABLE'
        entity['proof_basis'] = 'published_projection_not_independent_reverification'
        entity['observed_status'] = entity['facts'].get('verdict') if entity['kind'] == 'metric' else 'NOT_INDEPENDENTLY_VERIFIED'
        entity['observation_state'] = 'OBSERVED' if observed else 'UNKNOWN'
        if entity['kind'] == 'metric':
            metric = entity['facts']
            current = metric.get('current')
            value_is_numeric = type(current) in (int, float) and math.isfinite(current)
            refs = rows(metric.get('source_refs'))
            has_sources = bool(refs) and all(proof_reference(ref) for ref in refs)
            verified = (entity['evidence_class'] in NUMERIC_EVIDENCE
                        and metric.get('verdict') in ('PROVEN', 'VERIFIED', 'OBSERVED')
                        and value_is_numeric and has_sources)
            if verified:
                entity['proof_state'] = 'SOURCE_NUMERIC_OBSERVATION'
            elif metric.get('verdict') in ('UNMEASURED', 'UNKNOWN', 'NOT_PROVEN', 'UNAVAILABLE'):
                entity['proof_state'] = metric['verdict']
        entity['adjacency_count'] = len(self.adjacency[identity])
        return entity

    def _envelope(self, data, stamp, enforce_limit=True):
        result = {'schema_version': 'observer-query/v1', 'generation_id': self.generation,
                  'snapshot_digest': self.snapshot_digest, 'snapshot_digest_scope': 'canonical_json_content',
                  'generated_at': self.generated_at, 'served_at': stamp, 'state': self.state,
                  'freshness': freshness(self.generated_at, stamp), 'read_only': True,
                  'authorization_mode': 'single-user-loopback', 'role_is_authority': False,
                  'instruction_capable': False, 'data': data}
        result['response_digest'] = content_digest(result)
        if enforce_limit and len(json_bytes(result)) > MAX_RESPONSE_BYTES:
            raise QueryError(413, 'RESPONSE_BUDGET_EXCEEDED')
        return result

    def _controls(self):
        controls = [
            ('accept-setting', '接受设定或改预算', 'Principal + OMO', ['exact_scope', 'principal_authority', 'canonical_receipt']),
            ('create-work', '创建 BET 或 WorkPacket', 'OMO + Ledger/Spec owner', ['A1-A9', 'accepted_binding', 'workflow_claim']),
            ('dispatch', '分派或接续 Agent', 'OMO Workflow Mesh', ['A1-A9', 'actor_mandate', 'context_ack', 'lease_fence']),
            ('reconcile', '停止、重试或回滚', 'OMO Workflow Mesh', ['exact_attempt', 'effect_reconciliation', 'operation_authority']),
            ('memory-write', '沉淀记忆或晋升规则', 'Memory/Rule owner via OMO', ['provenance', 'review', 'accepted_successor']),
            ('value-verdict', '裁定个人价值', 'Principal value adjudication', ['real_outcome', 'human_verdict', 'frozen_metric_contract']),
        ]
        return [{'id': identity, 'title': title, 'canonical_owner': owner, 'prerequisites': needs,
                 'execution_enabled': False, 'interface_state': 'NOT_CONNECTED',
                 'blocked_reason': 'canonical_admission_and_effect_bridge_not_connected',
                 'next_action': '核对原有准入与操作合同；本机只可准备审议，不能执行。'}
                for identity, title, owner, needs in controls]

    def query(self, operation, params):
        if operation not in OPERATIONS or not isinstance(params, dict):
            raise QueryError(400, 'UNKNOWN_OPERATION')
        if set(params) - (OPERATIONS[operation] | {'generation'}):
            raise QueryError(400, 'UNKNOWN_QUERY_FIELD')
        if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 4096 or '\x00' in v for k, v in params.items()):
            raise QueryError(400, 'INVALID_QUERY')
        if 'generation' in params and params['generation'] != self.generation:
            raise QueryError(409, 'GENERATION_EXPIRED')
        stamp = self._now()
        if operation == 'manifest':
            data = {'service': 'zhixing-observer-read', 'operations': sorted(OPERATIONS),
                    'api_base': '/api/v1/', 'execution_enabled': False,
                    'documentation': {'api': str(Path(__file__).with_name('API.md')),
                                      'agent_reading': str(Path(__file__).with_name('AGENT-READING.md')),
                                      'interface': str(Path(__file__).with_name('INTERFACE.yaml'))},
                    'reading_sequence': ['manifest', 'summary', 'search', 'entity', 'neighbors', 'brief', 'canonical_authorized_reread',
                                            'scene_status', 'scene_graph'],
                    'scope': 'published_allowlisted_metadata_only', 'canonical_control_owner': 'OMO',
                    'context_pack_owner': 'ecos L4ContextPack; this response is not a ContextPack',
                    'lenses': list(LENSES), 'kinds': sorted({e['kind'] for e in self.entities.values()}),
                    'limits': {'list_default': 20, 'list_max': 50, 'neighbor_depth_max': 2,
                               'neighbor_max': 100, 'response_bytes': MAX_RESPONSE_BYTES,
                               'brief_min_bytes': 4096, 'brief_max_bytes': 65536},
                    'pinned_document': {'path': '/api/v1/document', 'required': ['id', 'generation', 'expected_sha256']},
                    'errors': ['GENERATION_EXPIRED', 'AMBIGUOUS', 'RESET_REQUIRED', 'RESPONSE_BUDGET_EXCEEDED'],
                    'legacy_document': 'unpinned; not suitable for exact-generation Agent reads'}
        elif operation == 'summary':
            attention = []
            for entity in self.entities.values():
                if entity['kind'] == 'gate' and entity['declared_status'].startswith('FAIL'):
                    attention.append({'id': entity['id'], 'title': entity['title'], 'type': 'observed_gate_failure',
                                      'description': entity['facts'].get('description'), 'next_action': entity['facts'].get('next')})
            attention += [{'id': gap.get('id'), 'title': gap.get('title'), 'type': gap.get('kind'),
                           'next_action': gap.get('next_action')} for gap in self.gaps]
            states = [{'id': text(key), 'status': item.get('status'),
                       'last_attempt_at': item.get('last_attempt_at'),
                       'freshness': freshness(item.get('last_success_at'), stamp)}
                      for key, item in sorted(self.sources.items()) if isinstance(item, dict)]
            data = {'entity_counts': dict(Counter(e['kind'] for e in self.entities.values())),
                    'entities_known': len(self.entities), 'edges_known': len(self.edges),
                    'ambiguous_id_count': len(self.duplicates), 'gap_count': len(self.gaps),
                    'attention': attention[:3], 'attention_total_known': len(attention),
                    'attention_order': 'observed_failures_then_known_gaps; not_business_priority',
                    'source_states': states, 'phase_plans': self.phase_plans,
                    'reference_cell': copy.deepcopy(self.reference_cell),
                    'environment_evidence': copy.deepcopy(self.environment_evidence),
                    'coverage': {'scope': 'published_projected_metadata', 'universe_complete': False,
                                 'private_memory_bodies': 'NOT_COLLECTED', 'raw_native_tool_logs': 'NOT_CONNECTED',
                                 'binding_completeness': 'UNPROVABLE'},
                    'sufficient_for_write': False, 'history_coverage': self.history_coverage,
                    'control_state': 'CANONICAL_ADMISSION_REQUIRED'}
        elif operation == 'search':
            data = self._search(params, stamp)
        elif operation == 'entity':
            identity = params.get('id', '')
            data = {'entity': self._entity(identity, stamp),
                    'gaps': self._applicable_gaps(identity),
                    'scope': 'single_projected_object_not_authority'}
        elif operation == 'neighbors':
            data = self._neighbors(params, stamp)
        elif operation == 'brief':
            return self._brief(params, stamp)
        elif operation == 'controls':
            data = {'items': self._controls(), 'execution_enabled': False}
        elif operation == 'ontology':
            from cockpit.observatory.ontology_model import export_ontology_schema
            data = export_ontology_schema()
            data['axioms_live'] = self.axioms or {}
        elif operation == 'lineage':
            from cockpit.observatory.strategy_projection import trace_lineage
            entity_id = params.get('id', '')
            direction = params.get('direction', 'both')
            depth = params.get('depth', '3')
            data = trace_lineage(self.trace, entity_id, direction=direction, max_depth=depth)
        elif operation == 'context_pack':
            from cockpit.observatory.rag_engine import HybridRAGEngine
            rag = getattr(self, '_rag_engine', None)
            if rag is None:
                rag = HybridRAGEngine()
                self._rag_engine = rag
            data = rag.get_context_pack(params.get('id', ''))
        elif operation == 'scene_status':
            data = self._scene_status(params)
        elif operation == 'scene_graph':
            data = self._scene_graph(params)
        else:
            previous = self.previous
            if previous is None or previous.generation == self.generation or params.get('from_generation') != previous.generation:
                raise QueryError(409, 'RESET_REQUIRED')
            old, new = previous.entities, self.entities
            added = sorted(set(new) - set(old))
            lost = sorted(set(old) - set(new))
            changed = sorted(k for k in set(new) & set(old) if new[k]['content_digest'] != old[k]['content_digest'])
            source_changed = sorted(k for k in set(new) & set(old) if new[k]['provenance_digest'] != old[k]['provenance_digest'])
            data = {'from_generation': previous.generation, 'added': added[:100],
                    'changed': changed[:100], 'source_changed': source_changed[:100], 'no_longer_observed': lost[:100],
                    'counts': {'added': len(added), 'changed': len(changed), 'source_changed': len(source_changed), 'no_longer_observed': len(lost)},
                    'truncated': any(len(x) > 100 for x in (added, changed, source_changed, lost)),
                    'scope': 'sampled_projection_difference_not_business_deletion_or_event_stream',
                    'source_coverage_comparable': bool(self.sources) and set(previous.sources) == set(self.sources)
                        and all(self.sources[k].get('status') == previous.sources[k].get('status') == 'OK' for k in self.sources)
                        and previous.scope == self.scope}
        return self._envelope(data, stamp)

    # ── Scene system queries (Phase D: Serena observatory integration) ──

    def _scene_kinds(self) -> set[str]:
        return {e['kind'] for e in self.entities.values()
                if e['kind'].startswith(('scene_', 'scene_system'))
                or e.get('id', '').startswith('scene_system:')}

    def _scene_status(self, params: dict) -> dict:
        kinds = ('scene_system:cards', 'scene_system:signal_poller',
                 'scene_system:journey_executions', 'scene_system:remote_hygiene',
                 'scene_system:service_keeper', 'scene_system:connectors',
                 'scene_system:bos_verifier')
        filter_kind = params.get('kind')
        status = {'sources': {}, 'entity_count': 0}
        for identity in kinds:
            entity = self.entities.get(identity)
            if entity is None:
                continue
            if filter_kind and entity['kind'] != filter_kind:
                continue
            status['entity_count'] += 1
            facts = entity['facts']
            if identity.endswith(':cards'):
                status['sources']['scene_cards'] = {
                    'total': facts.get('total'), 'with_trigger': facts.get('with_trigger'),
                    'lifecycle': {e['facts'].get('stage'): e['facts'].get('count')
                                  for e in self.entities.values()
                                  if e.get('kind') == 'scene_card_stage'}}
            elif identity.endswith(':signal_poller'):
                status['sources']['signal_poller'] = {
                    'watermark_entries': facts.get('watermark_entries'),
                    'scenes_with_triggers': facts.get('scenes_with_triggers'),
                    'last_poll': facts.get('last_poll')}
            elif identity.endswith(':journey_executions'):
                status['sources']['journey_executions'] = {
                    'total': facts.get('total'), 'escalated': facts.get('escalated'),
                    'succeeded': facts.get('succeeded'), 'failed': facts.get('failed'),
                    'auto_complete_rate': facts.get('auto_complete_rate')}
            elif identity.endswith(':remote_hygiene'):
                status['sources']['remote_hygiene'] = {
                    'origin_canonical': facts.get('origin_canonical'),
                    'origin_push_canonical': facts.get('origin_push_canonical'),
                    'last_fix_remotes_run': facts.get('last_fix_remotes_run')}
            elif identity.endswith(':service_keeper'):
                status['sources']['service_keeper'] = facts.get('services', [])
            elif identity.endswith(':connectors'):
                status['sources']['connectors'] = {
                    'total': facts.get('total'),
                    'wired': [c for c in facts.get('wired_to_scenes', []) or []],
                    'unwired': [c for c in facts.get('unwired_available', []) or []]}
            elif identity.endswith(':bos_verifier'):
                status['sources']['bos_verifier'] = {
                    'last_run_ok': facts.get('last_run_ok'),
                    'last_run_errors': facts.get('last_run_errors')}
        status['available_kinds'] = sorted(self._scene_kinds())
        return status

    def _scene_graph(self, params: dict) -> dict:
        root = params.get('root', 'scene_system:signal_poller')
        depth = 2
        try:
            depth = int(params.get('depth', '2'))
        except (TypeError, ValueError):
            pass
        depth = max(0, min(depth, 3))
        nodes, visited = [], {root}
        frontier = [(root, 0)]
        while frontier:
            current, level = frontier.pop(0)
            visited.add(current)
            nodes.append({'id': current, 'level': level,
                          'facts': self.entities.get(current, {}).get('facts', {})})
            if level >= depth:
                continue
            for edge in self.adjacency.get(current, []):
                target = edge.get('to') or edge.get('from')
                if target == current or target in visited:
                    continue
                visited.add(target)
                frontier.append((target, level + 1))
        return {'root': root, 'depth': depth, 'graph': nodes,
                'scope': 'projected_scene_system_topology_only'}

    def _applicable_gaps(self, identity):
        found = []
        entity = self.entities.get(identity, {})
        for gap in self.gaps:
            ref = gap.get('entity_id')
            targets = self.aliases.get(ref, set()) if isinstance(ref, str) else set()
            basis = None
            if ref == identity:
                basis = 'explicit_entity_id'
            elif identity in targets:
                basis = 'explicit_raw_id' if len(targets) == 1 else 'AMBIGUOUS_RAW_ID'
            elif mapping(gap.get('source')).get('path') and mapping(gap.get('source')).get('path') == mapping(entity.get('source')).get('path'):
                basis = 'same_source_file_not_entity_binding'
            if basis:
                found.append(dict(copy.deepcopy(gap), association_basis=basis))
        return found

    def _search(self, params, stamp):
        query, kind = params.get('q', ''), params.get('kind', '')
        if len(query) > 256 or len(kind) > 80:
            raise QueryError(400, 'QUERY_TOO_LONG')
        limit = integer(params, 'limit', 20, 1, 50)
        normalized = query.casefold().strip()
        def searchable(item):
            fields = [item['id'], item['title'], item['kind'], text(item['source'].get('path'))]
            fields += [text(item['facts'].get(key)) for key in ('provider', 'owner', 'owner_role', 'role', 'uri', 'raw_id', 'bet_id')]
            return ' '.join(fields).casefold()
        matches = [item for item in self.entities.values() if (not kind or item['kind'] == kind)
                   and (not normalized or normalized in searchable(item))]
        matches.sort(key=lambda item: (0 if normalized and normalized == item['id'].casefold() else 1,
                                       item['kind'], item['title'], item['id']))
        signature = content_digest({'q': query, 'kind': kind, 'limit': limit, 'sort': 'exact-kind-title-id-v1'})
        offset = 0
        if 'cursor' in params:
            try:
                raw = base64.b64decode(params['cursor'] + '=' * (-len(params['cursor']) % 4), altchars=b'-_', validate=True)
                cursor = json.loads(raw)
                if not isinstance(cursor, dict) or set(cursor) != {'generation', 'signature', 'offset'}:
                    raise ValueError()
                if cursor['generation'] != self.generation:
                    raise QueryError(409, 'GENERATION_EXPIRED')
                offset = cursor['offset']
                if cursor['signature'] != signature or type(offset) is not int or not 0 <= offset <= len(matches):
                    raise ValueError()
            except (ValueError, UnicodeDecodeError, TypeError, KeyError):
                raise QueryError(400, 'INVALID_CURSOR') from None
        selected = matches[offset:offset + limit]
        items = [self._entity(item['id'], stamp) if item['id'] not in self.duplicates
                 else {'id': item['id'], 'kind': item['kind'], 'title': item['title'], 'proof_state': 'AMBIGUOUS'}
                 for item in selected]
        next_offset = offset + len(items)
        cursor = None
        if next_offset < len(matches):
            cursor = base64.urlsafe_b64encode(json_bytes({'generation': self.generation, 'signature': signature,
                                                        'offset': next_offset})).decode().rstrip('=')
        return {'items': items, 'returned_count': len(items), 'total_known': len(matches), 'next_cursor': cursor,
                'scope': 'projected_id_title_type_source_provider_owner_metadata', 'truncated': False}

    def _neighbors(self, params, stamp):
        identity = params.get('id', '')
        self._entity(identity, stamp)
        direction = params.get('direction', 'both')
        if direction not in ('both', 'in', 'out'):
            raise QueryError(400, 'INVALID_DIRECTION')
        depth = integer(params, 'depth', 1, 1, 2)
        limit = integer(params, 'limit', 30, 1, 100)
        seen, queue, identities, edges, edge_keys, unresolved = {identity}, deque([(identity, 0)]), [], [], set(), set()
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for edge in self.adjacency[current]:
                if direction == 'in' and edge['to'] != current or direction == 'out' and edge['from'] != current:
                    continue
                key = (edge['from'], edge['to'], edge['relation'], edge['relation_basis'])
                if key not in edge_keys:
                    edge_keys.add(key); edges.append(edge)
                neighbor = edge['to'] if edge['from'] == current else edge['from']
                if neighbor not in self.entities or neighbor in self.duplicates:
                    unresolved.add(neighbor)
                if neighbor not in seen:
                    seen.add(neighbor)
                    if neighbor in self.entities and neighbor not in self.duplicates:
                        identities.append(neighbor)
                        queue.append((neighbor, level + 1))
        included = identities[:limit]
        return {'items': [self._entity(key, stamp) for key in included], 'edges': copy.deepcopy(edges[:200]),
                'returned_count': len(included), 'total_known': len(identities),
                'unresolved_refs': sorted(unresolved)[:100],
                'truncated': len(identities) > limit or len(edges) > 200 or len(unresolved) > 100,
                'depth': depth, 'direction': direction,
                'scope': 'bounded_graph_adjacency_not_complete_business_impact'}

    def _brief(self, params, stamp):
        lens = params.get('lens', 'overview')
        if lens not in LENSES:
            raise QueryError(400, 'INVALID_LENS')
        budget = integer(params, 'budget_bytes', 16384, 4096, 65536)
        focal = self._entity(params.get('id', ''), stamp)
        neighbors = self._neighbors({'id': focal['id'], 'depth': '1', 'limit': '100'}, stamp)
        common_ids = ('ZX-DOC-AGENT-CONTEXT-001', 'ZX-DOC-LIB-ENTRY-001')
        pointers = [{'document_id': doc.get('id'), 'title': doc.get('title'), 'source_ref': doc.get('path'),
                     'sha256': doc.get('sha256'), 'authority_class': doc.get('authority_class'),
                     'observation_scope': doc.get('observation_scope'),
                     'approval_state': doc.get('approval_state'), 'required': True,
                     'selection_reason': 'shared_navigation_and_authority_boundary; canonical reread required'}
                    for doc in self.documents if doc.get('id') in common_ids]
        for pointer in pointers:
            complete = (bool(pointer['source_ref']) and isinstance(pointer['sha256'], str)
                        and bool(re.fullmatch(r'[a-fA-F0-9]{64}', pointer['sha256']))
                        and pointer['observation_scope'] == 'content_hash_and_heading_index'
                        and sum(doc.get('document_id') == pointer['document_id'] for doc in pointers) == 1)
            pointer['validation_state'] = 'POINTER_ONLY_REREAD_REQUIRED' if complete else 'INVALID_REFERENCE'
        data = {'lens': lens, 'focus': focal, 'is_context_pack': False, 'sufficient_for_write': False,
                'lens_mode': 'reading_label_only_same_material_selection',
                'common_pointers': pointers, 'related': [], 'required_missing': [key for key in common_ids
                     if not any(doc.get('document_id') == key and doc['validation_state'] == 'POINTER_ONLY_REREAD_REQUIRED' for doc in pointers)],
                'stop_conditions': ['Observer response grants no write/effect authority.',
                    'Reread canonical role, accepted Spec, WorkPacket, claim and operation authority before acting.',
                    'Stop on unresolved identity, stale source, version conflict or missing required reference.'],
                'unknowns': neighbors['unresolved_refs'], 'omissions': [],
                'budget': {'requested_bytes': budget, 'effective_bytes': budget},
                'token_count': {'state': 'UNMEASURED', 'reason': 'provider tokenizer not selected'}}
        applicable = self._applicable_gaps(focal['id'])
        data['applicable_gaps'] = applicable
        data['applicable_gap_count'] = len(applicable)
        data['authority_validation'] = 'NOT_PERFORMED'
        if applicable:
            data['unknowns'].append('Applicable gaps require canonical review before any action.')
        def size():
            return len(json_bytes(self._envelope(data, stamp, enforce_limit=False)))
        if size() > budget - 256:
            data['focus']['facts'] = {}
            data['omissions'].append({'reason': 'focus_facts_excluded_to_preserve_boundaries'})
        if size() > budget - 256 and applicable:
            data['applicable_gaps'] = []
            data['omissions'].append({'reason': 'gap_details_budget', 'count': len(applicable)})
        for item in neighbors['items']:
            data['related'].append({'entity': item, 'selection_reason': 'direct_graph_relation_not_inferred_permission'})
            if size() > budget - 256:
                data['related'].pop()
                data['omissions'].append({'reason': 'response_byte_budget', 'omitted_related': len(neighbors['items']) - len(data['related'])})
                break
        if neighbors['truncated']:
            data['omissions'].append({'reason': 'neighbor_window', 'total_known': neighbors['total_known']})
        if size() > budget:
            data['focus']['facts'] = {}
            data['omissions'].append({'reason': 'focus_facts_excluded_to_preserve_boundaries'})
        result = self._envelope(data, stamp)
        for _ in range(4):
            used = len(json_bytes(result))
            if data['budget'].get('used_bytes') == used:
                break
            data['budget']['used_bytes'] = used
            result = self._envelope(data, stamp)
        if len(json_bytes(result)) > budget:
            raise QueryError(413, 'REQUIRED_CONTEXT_EXCEEDS_BUDGET')
        return result


class SnapshotStore:
    """Cache immutable parsed generations. Missing/corrupt live files never look fresh."""
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._key = None
        self._index = None

    @staticmethod
    def _read(path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SNAPSHOT_BYTES:
                    raise QueryError(503, 'SNAPSHOT_BUDGET_OR_TYPE_INVALID')
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > MAX_SNAPSHOT_BYTES or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise QueryError(503, 'SNAPSHOT_CHANGED_DURING_READ')
            data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite')))
            return data, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError):
            raise QueryError(503, 'SNAPSHOT_UNAVAILABLE') from None

    def load(self):
        with self._lock:
            # Opening with nofollow also validates a replaced path before reuse.
            data, key = self._read(self.path)
            if key != self._key:
                index = ObservationIndex(data)
                try:
                    old, _ = self._read(self.path.with_name('previous-snapshot.json'))
                    previous = ObservationIndex(old)
                    if previous.generation != index.generation:
                        index.previous = previous
                except QueryError:
                    pass
                self._index, self._key = index, key
            return self._index


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read published observer metadata; never dispatch or authorize effects.')
    parser.add_argument('operation', choices=sorted(OPERATIONS))
    for key in sorted(set().union(*OPERATIONS.values()) | {'generation'}):
        parser.add_argument('--' + key.replace('_', '-'), dest=key)
    args = vars(parser.parse_args(argv))
    operation = args.pop('operation')
    params = {key: value for key, value in args.items() if value is not None}
    try:
        result = SnapshotStore(Path(__file__).with_name('current.json')).load().query(operation, params)
    except QueryError as error:
        print(json.dumps({'error': error.code, 'status': error.status, 'read_only': True}))
        return 1
    sys.stdout.buffer.write(json_bytes(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
