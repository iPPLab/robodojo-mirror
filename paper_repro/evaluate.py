"""Plan or run a case through a configured native RoboDojo entry point."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .metrics import validate_record
from .scenes import scene_settings


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def case_context(args):
    protocol = load_json(CONFIG_DIR / "paper_main.json")
    policy = protocol["policies"].get(args.policy)
    if policy is None or args.task not in protocol["tasks"]:
        raise ValueError("Choose a policy and task from configs/paper_main.json")
    if min(args.layout, args.seed) < 0:
        raise ValueError("Layout and seed must be nonnegative IDs")
    revision = load_json(CONFIG_DIR / "corrected_dual.json") if args.corrected_dual else None
    scene = scene_settings(protocol, args.policy, args.condition, revision)
    return dict(
        policy=args.policy,
        task=args.task,
        condition=args.condition,
        layout=args.layout,
        seed=args.seed,
        **scene,
    )


def field(document, path):
    for part in path:
        document = document[part]
    return document


def evaluate_case(runtime_path, case):
    runtime_path = runtime_path.resolve()
    runtime = load_json(runtime_path)
    runtime_root = runtime_path.parent
    runner = runtime[case["policy"]][case["placement_revision"]][case["condition"]]
    cwd = (runtime_root / runner.get("cwd", ".")).resolve(strict=True)
    context = dict(case, runtime_root=str(runtime_root))
    result_path = cwd / runner["result"].format_map(context)
    if result_path.exists() or result_path.is_symlink():
        raise ValueError(f"Native result already exists; use a fresh run path: {result_path}")
    identity = runner["identity_fields"]
    if not {"task", "layout", "seed", "condition"} <= identity.keys():
        raise ValueError("Map task, layout, seed, and condition in identity_fields")
    completion = runner.get("completion")
    marker = cwd / completion["file"].format_map(context) if completion else None
    if marker is not None and (marker.exists() or marker.is_symlink()):
        raise ValueError(f"Completion record already exists: {marker}")
    if marker is None and "status_field" not in runner:
        raise ValueError("Configure a native status field or a completion record")
    argv = [arg.format_map(context) for arg in runner["argv"]]
    environment = os.environ.copy()
    environment.update({key: value.format_map(context)
                        for key, value in runner.get("env", {}).items()})
    subprocess.run(argv, cwd=cwd, env=environment, check=True, stdout=sys.stderr)

    native = load_json(result_path)
    # Check the identifiers available in the native artifact against the requested slot.
    for key, path in identity.items():
        expected = runner.get("identity_values", {}).get(key, "{" + key + "}")
        if str(field(native, path)) != expected.format_map(context):
            raise ValueError(f"Native result identity mismatch for {key}: {result_path}")
    source = str(result_path.resolve().relative_to(runtime_root)) if (
        result_path.resolve().is_relative_to(runtime_root)
    ) else str(result_path.resolve())
    status = field(native, runner["status_field"]) if "status_field" in runner else "complete"
    finished = status in runner.get("completed_values", ["complete"])
    if marker is not None:
        marker_status = field(load_json(marker), completion["field"])
        finished = finished and marker_status in completion["values"]
    record = dict(
        case,
        status="complete" if finished else f"native:{status}",
        source=source,
        contact_source="unavailable",
        contact=None,
    )
    if finished:
        success = field(native, runner["success_field"])
        if success not in (False, True) or type(success) not in (bool, int):
            raise ValueError("Native success must be a boolean or a binary integer")
        score = field(native, runner["score_field"])
        scale = runner["score_max"]
        if type(score) not in (int, float) or scale not in (1, 100):
            raise ValueError("Native score must be numeric with scale 1 or 100")
        record.update(status="complete", success=bool(success), score=score / scale)
    if case["static_vertical_colliders"] and "contact_field" in runner:
        record["contact"] = field(native, runner["contact_field"])
        record["contact_source"] = runner["contact_source"]
        if record["contact"] is not None and "contact_threshold" in runner:
            count = record["contact"]
            if type(count) not in (int, float) or not 0 <= count < float("inf"):
                raise ValueError("Native contact count must be finite and nonnegative")
            record["contact"] = count > runner["contact_threshold"]
        if record["contact"] is None:
            record["contact_source"] = "unavailable"
    if not case["static_vertical_colliders"]:
        record["contact_source"] = "not_applicable"
    validate_record(record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--layout", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--corrected-dual", action="store_true")
    parser.add_argument("--runtime", type=Path, help="Run using this native runner manifest; omit to print the case")
    args = parser.parse_args()
    try:
        case = case_context(args)
        record = evaluate_case(args.runtime, case) if args.runtime else case
        print(json.dumps(record, allow_nan=False))
    except (KeyError, IndexError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Evaluation error: {exc}\n")


if __name__ == "__main__":
    main()
