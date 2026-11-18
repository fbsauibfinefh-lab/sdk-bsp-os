#!/usr/bin/env python3
"""四视图留一实验，固定候选、H03、厂商折和每个条件的选参预算。"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np

from bspforge.common import file_sha256, read_json, write_json
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments
from evaluate_multiview_channel_ablations import PARAMETERS, all_names
from evaluate_multiview_effect_ranker import record_for_scores
from evaluate_multiview_lambdamart import VARIANTS, candidate_row, numeric_feature_names, objective


FUSIONS = {
    'static_score', 'multi-channel-rrf', 'layer-route-score',
    'operation-contract-retrieval', 'signature-contract-retrieval',
    'graph-neighbor-support', 'semantic-conflict',
}
CODE = {'full_code_cosine', 'focused_code_cosine', 'full_focus_cosine', 'code-embedding', 'cross-reranker'}
STRUCTURAL_GRAPH = {
    'hw-api-boundary-depth', 'hw-callee-fanout', 'hw-caller-fanin',
    'hw-composite-likelihood', 'hw-example-likelihood', 'hw-internal-callback-likelihood',
    'hw-os-adapter-likelihood', 'hw-public-boundary', 'hw-signature-contract', 'hw-static-internal',
}


def removal_set(names: list[str], view: str) -> set[str]:
    interface = {n for n in names if n.startswith('field-')}
    hardware = {n for n in names if n.startswith('hw-')}
    structure = {n for n in names if not n.startswith('operation::')} - interface - CODE - hardware
    selected = {
        'full': set(),
        'without-interface': interface | FUSIONS,
        'without-code': CODE | {'semantic-conflict'},
        'without-hardware': hardware | FUSIONS,
        'without-structure': structure | STRUCTURAL_GRAPH | FUSIONS,
    }[view]
    return selected & set(names)


def paired(records: list[dict], reference: list[dict], groups: list[dict], seed: int) -> dict:
    ref = {r['group_id']: r for r in reference}
    source = {g['group_id']: g['independence_group'] for g in groups}
    keys = ('precision_at_1', 'recall_at_5', 'hit_at_5', 'map', 'ndcg_at_10')
    rng = np.random.default_rng(seed)
    result = {}
    for metric in keys:
        def value(row):
            if metric == 'hit_at_5':
                return float(any(item['rank'] <= 5 for item in row['positive_ranks']))
            return row['metrics'][metric]
        delta = np.array([value(r) - value(ref[r['group_id']]) for r in records])
        by_source = defaultdict(list)
        for r, value in zip(records, delta, strict=True):
            by_source[source[r['group_id']]].append(float(value))
        source_values = list(by_source.values())
        draws = rng.integers(0, len(source_values), size=(10000, len(source_values)))
        sums = np.array([sum(v) for v in source_values])
        sizes = np.array([len(v) for v in source_values])
        cluster = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
        query_draws = rng.integers(0, len(delta), size=(10000, len(delta)))
        result[metric] = {
            'delta_vs_full': float(delta.mean()),
            'source_cluster_bootstrap_95_ci': np.quantile(cluster, [.025, .975]).tolist(),
            'query_bootstrap_95_ci': np.quantile(delta[query_draws].mean(axis=1), [.025, .975]).tolist(),
            'wins_ties_losses': [int((delta > 1e-12).sum()), int((abs(delta) <= 1e-12).sum()), int((delta < -1e-12).sum())],
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20260903)
    args = parser.parse_args()
    started = time.perf_counter()
    root = Path('experiments/generated/h03-20260831')
    dataset_path = root / 'hardware-effect-h03-v0.1.json'
    dataset = read_json(dataset_path)
    groups = [g for g in dataset['groups'] if g['role'] == 'train']
    cache = MultiViewEffectCache(root / 'jina-code-embeddings-h03-v0.2.json', root / 'jina-code-embeddings-h03-v0.2.npz', root / 'jina-multiview-effect-h03-v0.3.json', root / 'jina-multiview-effect-h03-v0.3.npz')
    numeric = numeric_feature_names(groups)
    names = all_names(numeric)
    assert len(groups) == 284 and len(names) == 83
    values = {}
    labels = {}
    penalties = {}
    for group in groups:
        gid = group['group_id']
        values[gid] = np.asarray([candidate_row(group, c, cache, numeric) for c in group['candidates']], dtype=np.float64)
        labels[gid] = np.array([c['label'] for c in group['candidates']], dtype=np.int32)
        penalties[gid] = np.array([operation_constraint_penalty(c, group['operation_id']) for c in group['candidates']])

    def fit(items: list[dict], mask: list[int], params: dict, seed: int):
        x = np.concatenate([values[g['group_id']][:, mask] for g in items])
        y = np.concatenate([labels[g['group_id']] for g in items])
        model = lgb.LGBMRanker(**{'objective': 'lambdarank', 'metric': 'ndcg', 'reg_lambda': 1.5, 'reg_alpha': .25, 'random_state': seed, 'verbosity': -1, 'n_jobs': 8, **params})
        model.fit(x, y, group=[len(g['candidates']) for g in items])
        return model

    def evaluate(model, items: list[dict], mask: list[int], view: str):
        rows = []
        for group in items:
            gid = group['group_id']
            scores = model.predict(values[gid][:, mask])
            if view != 'without-structure':
                scores = scores - 8.0 * penalties[gid]
            row = record_for_scores(group, list(map(float, scores)))
            row['independence_group'] = group['independence_group']
            rows.append(row)
        return rows

    variants = ('full', 'without-interface', 'without-code', 'without-hardware', 'without-structure')
    records = defaultdict(list)
    fold_reports = []
    if (args.output / 'checkpoint.json').exists():
        saved = read_json(args.output / 'checkpoint.json')
        records.update(saved['records'])
        fold_reports = saved['fold_reports']
    assignments = fold_assignments(groups, 5)
    for view in variants:
        removed = removal_set(names, view)
        mask = [i for i, name in enumerate(names) if name not in removed]
        for fold, test_ids in enumerate(assignments, 1):
            if any(r['view'] == view and r['fold'] == fold for r in fold_reports):
                continue
            outer = [g for g in groups if g['independence_group'] not in test_ids]
            test = [g for g in groups if g['independence_group'] in test_ids]
            validation_ids = fold_assignments(outer, 4)[0]
            inner = [g for g in outer if g['independence_group'] not in validation_ids]
            validation = [g for g in outer if g['independence_group'] in validation_ids]
            selections = {}
            for name, params in VARIANTS.items():
                model = fit(inner, mask, params, args.seed + fold * 100)
                metrics = aggregate(evaluate(model, validation, mask, view))
                selections[name] = round(objective(metrics), 6)
            chosen = max(VARIANTS, key=lambda n: (selections[n], n))
            model = fit(outer, mask, VARIANTS[chosen], args.seed + fold * 10)
            rows = evaluate(model, test, mask, view)
            records['nested/' + view].extend(rows)
            fixed = fit(outer, mask, PARAMETERS, 20260905 + fold)
            fixed_rows = evaluate(fixed, test, mask, view)
            records['fixed/' + view].extend(fixed_rows)
            fold_reports.append({'view': view, 'fold': fold, 'test_sources': sorted(test_ids), 'validation_sources': sorted(validation_ids), 'selected_variant': chosen, 'inner_objectives': selections, 'retained_columns': [names[i] for i in mask], 'removed_columns': sorted(removed)})
            write_json(args.output / 'checkpoint.json', {'records': records, 'fold_reports': fold_reports})
            print(json.dumps({'view': view, 'fold': fold, 'selected': chosen, 'metrics': aggregate(rows)}, ensure_ascii=False), flush=True)
    old = read_json(Path('experiments/operation-ranking/h03-unified-rerun-20260908/results-multiview-lambdamart-h03-v0.3.json'))
    old_records = old['cross_validation']['records']['multiview-lambdamart-nested']
    old_metrics = aggregate(old_records)
    new_metrics = aggregate(records['nested/full'])
    reproduction = {'historical': old_metrics, 'new': new_metrics, 'matches_rounded_metrics': old_metrics == new_metrics}
    result = {
        'protocol': {'truth': 'H03 unchanged', 'queries': len(groups), 'sources': len({g['independence_group'] for g in groups}), 'folds': [sorted(x) for x in assignments], 'seed': args.seed, 'n_jobs': 8, 'nested_budget': VARIANTS, 'fixed_capacity': PARAMETERS, 'candidate_pool_fixed': True, 'dependent_fusion_columns_removed': True, 'structure_ablation_removes_post_score_constraint': True, 'upstream_candidate_pool_not_rebuilt': True, 'note': 'Feature-block ablation; candidate recall and overlapping raw source information are held fixed, not a counterfactual SDK extraction experiment.'},
        'inputs': {str(dataset_path): file_sha256(dataset_path)},
        'features': names,
        'historical_full_reproduction': reproduction,
        'metrics': {name: aggregate(items) for name, items in records.items()},
        'paired': {name: paired(items, records[name.split('/')[0] + '/full'], groups, args.seed) for name, items in records.items() if not name.endswith('/full')},
        'records': records, 'fold_reports': fold_reports,
        'elapsed_this_invocation_seconds': time.perf_counter() - started,
        'elapsed_note': 'Checkpoint-resumable invocation time; not cumulative training time. Do not use as training benchmark.',
    }
    write_json(args.output / 'results.json', result)
    with (args.output / 'metrics.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['condition', *new_metrics])
        writer.writeheader()
        writer.writerows({'condition': name, **m} for name, m in result['metrics'].items())
    print(json.dumps({'metrics': result['metrics'], 'reproduction': reproduction}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
