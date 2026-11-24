"""Aggregate paired RoboDojo native outcomes from JSON Lines."""

import argparse
from collections import defaultdict
import json
from math import isfinite
from pathlib import Path
import random
from statistics import fmean
import sys


def validate_record(row):
    if not isinstance(row, dict):
        raise ValueError("An episode record must be a JSON object")
    for name in ("policy", "task", "condition", "status", "source", "placement_revision"):
        if not isinstance(row.get(name), str) or not row[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    for name in ("layout", "seed"):
        if type(row.get(name)) is not int or row[name] < 0:
            raise ValueError(f"{name} must be a nonnegative integer ID")
    if row["status"] == "complete":
        if type(row.get("success")) is not bool:
            raise ValueError("A completed episode requires a boolean success")
        score = row.get("score")
        if type(score) not in (int, float) or not isfinite(score) or not 0 <= score <= 1:
            raise ValueError("A completed episode requires a native score in [0, 1]")
    elif row.get("score") is not None or row.get("success") is not None:
        raise ValueError("An incomplete episode cannot carry evaluated outcomes")

    contact = row.get("contact")
    source = row.get("contact_source", "unavailable")
    if source not in ("unavailable", "not_applicable", "native", "replay"):
        raise ValueError("Invalid contact measurement source")
    if source in {"native", "replay"}:
        if type(contact) is not bool:
            raise ValueError("A valid contact measurement requires a boolean")
    elif contact is not None:
        raise ValueError("A contact flag requires a valid measurement source")


def index_records(protocol, rows):
    index = defaultdict(dict)
    for row in rows:
        validate_record(row)
        policy, task, condition = (row[k] for k in ("policy", "task", "condition"))
        if policy not in protocol["policies"] or task not in protocol["tasks"]:
            raise ValueError(f"Unknown policy or task: {policy}/{task}")
        if condition in protocol["controls"] and policy in protocol["control_policies"]:
            continue
        if condition not in protocol["conditions"]:
            raise ValueError(f"Unknown condition for {policy}: {condition}")
        if row["placement_revision"] != protocol["protocol_revision"]:
            raise ValueError("The main-table aggregator requires the paper placement revision")
        slot = row["layout"], row["seed"]
        cell = policy, task, condition
        if slot in index[cell]:
            raise ValueError(f"Duplicate episode {cell} {slot}; resolve replacements before aggregation")
        if row["status"] == "complete":
            index[cell][slot] = row
        else:
            # Remember incomplete slots to detect duplicates, but exclude them from scoring.
            index[cell][slot] = None
    return index


def validate_policy(protocol, index, policy):
    expected = protocol["policies"][policy]
    conditions = protocol["conditions"]
    for task in protocol["tasks"]:
        baseline = {slot for slot, row in index[policy, task, conditions[0]].items() if row}
        by_layout = defaultdict(set)
        for layout, seed in baseline:
            by_layout[layout].add(seed)
        if (len(by_layout) != expected["layouts_per_task"]
                or any(len(seeds) != expected["runs_per_layout"] for seeds in by_layout.values())
                or len({frozenset(seeds) for seeds in by_layout.values()}) != 1):
            raise ValueError(f"{policy}/{task}: incomplete baseline layout/seed coverage")
        for condition in conditions[1:]:
            actual = {slot for slot, row in index[policy, task, condition].items() if row}
            if actual != baseline:
                raise ValueError(
                    f"{policy}/{task}/{condition}: unmatched slots "
                    f"(missing={sorted(baseline - actual)}, extra={sorted(actual - baseline)})"
                )


def percentile(sorted_values, quantile):
    position = quantile * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (position - lower) * (sorted_values[upper] - sorted_values[lower])


def bootstrap_interval(task_layout_drops, replicates, seed):
    rng = random.Random(seed)
    # Drawing a paired drop per layout is equivalent to drawing every seed
    # and condition in that layout together, then taking their mean drop.
    samples = [
        100 * fmean(fmean(rng.choices(layouts, k=len(layouts))) for layouts in task_layout_drops)
        for _ in range(replicates)
    ]
    samples.sort()
    return [percentile(samples, quantile) for quantile in (0.025, 0.975)]


def aggregate(protocol, rows, policies=None, replicates=None, seed=20261113):
    if replicates is None:
        replicates = protocol["bootstrap_replicates"]
    if replicates <= 0:
        raise ValueError("Bootstrap replicates must be positive")
    index = index_records(protocol, rows)
    conditions = protocol["conditions"]
    baseline, *mirrors = conditions
    result = {}
    for policy in policies if policies else protocol["policies"]:
        validate_policy(protocol, index, policy)
        task_results = {}
        layout_drops = []
        for task in protocol["tasks"]:
            cells = {
                condition: {slot: row for slot, row in index[policy, task, condition].items() if row}
                for condition in conditions
            }
            task_results[task] = {}
            for condition, episodes in cells.items():
                measured = defaultdict(list)
                for row in episodes.values():
                    if row.get("contact") is not None:
                        measured[row["contact_source"]].append(row["contact"])
                task_results[task][condition] = {
                    "episodes": len(episodes),
                    "score_pct": 100 * fmean(row["score"] for row in episodes.values()),
                    "success_rate_pct": 100 * fmean(row["success"] for row in episodes.values()),
                    "contact_by_source": {
                        source: {"episodes": len(flags), "contact_episodes": sum(flags),
                                 "episode_rate_pct": 100 * fmean(flags)}
                        for source, flags in measured.items()
                    },
                }

            by_layout = defaultdict(list)
            for slot, row in sorted(cells[baseline].items()):
                difference = row["success"] - fmean(cells[c][slot]["success"] for c in mirrors)
                by_layout[slot[0]].append(difference)
            layout_drops.append([fmean(values) for values in by_layout.values()])

        means = {
            cond: {
                metric: fmean(task[cond][metric] for task in task_results.values())
                for metric in ("score_pct", "success_rate_pct")
            }
            for cond in conditions
        }
        drops = {
            metric: fmean(means[baseline][metric] - means[cond][metric] for cond in mirrors)
            for metric in ("score_pct", "success_rate_pct")
        }
        result[policy] = {
            "tasks": task_results,
            "macro_average": means,
            "mean_score_drop_points": drops["score_pct"],
            "mean_success_drop_pp": drops["success_rate_pct"],
            "success_drop_ci95_pp": bootstrap_interval(layout_drops, replicates, seed),
        }
    return result


def read_jsonl(stream):
    for number, line in enumerate(stream, 1):
        if line.strip():
            try:
                row = json.loads(line)
                validate_record(row)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Input line {number}: {exc}") from exc
            yield row


def main():
    config_path = Path(__file__).resolve().parents[1] / "configs/paper_main.json"
    protocol = json.loads(config_path.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episodes", help="Normalized JSONL file, or '-' for stdin")
    parser.add_argument("--policy", action="append", choices=protocol["policies"])
    parser.add_argument("--replicates", type=int)
    parser.add_argument("--seed", type=int, default=20261113)
    args = parser.parse_args()
    try:
        if args.episodes == "-":
            report = aggregate(protocol, read_jsonl(sys.stdin), args.policy, args.replicates, args.seed)
        else:
            with open(args.episodes, encoding="utf-8") as stream:
                report = aggregate(protocol, read_jsonl(stream), args.policy, args.replicates, args.seed)
        print(json.dumps(report, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Metrics error: {exc}\n")


if __name__ == "__main__":
    main()
