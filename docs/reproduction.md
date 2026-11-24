# Reproduction

Use the [README](../README.md#usage) to run a new policy evaluation with the RoboDojo-Mirror scene package. This guide covers the historical paper protocol and the tools for planning cases and aggregating recorded outcomes.

## Paper protocol

[The main configuration](../configs/paper_main.json) specifies eight manipulation tasks and four scene conditions. A case is identified by policy, task, scene condition, layout ID, and policy seed. Pair the layout and policy seed across all four conditions and use the original RoboDojo success signals and native scores.

Each policy uses five layouts per task. WALL-OSS, VPP2, Awomo-0.5, and Rex-M1 Preview use three policy seeds per layout. GPT-6-Astra uses one execution per layout. The same configuration lists the geometry-matched panel controls used by WALL-OSS and Awomo-0.5.

Historical paper results use the `paper` placement revision. [The corrected dual-mirror configuration](../configs/corrected_dual.json) defines separate offsets along the two outward support-plane normals. Keep results obtained with revised placement separate from the historical main-table aggregation.

## Plan or run a case

From the repository root, print a case plan:

```bash
python -m paper_repro.evaluate \
  --policy wall_oss --task cover_blocks --condition dual_mirror --layout 0 --seed 0
```

Add `--runtime runtime.json` only if you have a compatible native runner and its assets, policy adapter, and checkpoint. Use your own trusted runtime manifest. Its keys are policy, placement revision, and condition. Each entry maps the runner's command, case identifiers, completion status, and result fields. Here is an example for a separately supplied `native_runner.py` that writes one result for a fresh case:

```json
{
  "wall_oss": {
    "paper": {
      "dual_mirror": {
        "cwd": ".",
        "argv": [
          "python", "native_runner.py", "--task", "{task}",
          "--condition", "{condition}", "--layout", "{layout}",
          "--seed", "{seed}", "--output", "outputs/{condition}-{layout}-{seed}.json"
        ],
        "result": "outputs/{condition}-{layout}-{seed}.json",
        "status_field": ["status"],
        "completed_values": ["complete"],
        "identity_fields": {
          "task": ["task"], "condition": ["condition"],
          "layout": ["layout"], "seed": ["seed"]
        },
        "success_field": ["success"],
        "score_field": ["score"],
        "score_max": 1
      }
    }
  }
}
```

`cwd` is relative to the manifest directory. Result and optional completion record paths are relative to `cwd`. For an evaluator with a separate completion record, use `completion` with `file`, `field`, and `values`. If the runner uses different condition identifiers, map those with `identity_values`. Use `score_max: 100` when native scores are on a 0–100 scale. Use a fresh output path for every case.

## Aggregate results

Provide one normalized JSON object per line. This example illustrates the format for a single completed episode:

```json
{"policy":"wall_oss","task":"cover_blocks","condition":"dual_mirror","layout":0,"seed":0,"placement_revision":"paper","status":"complete","success":false,"score":0.0,"source":"episodes/cover_blocks-dual_mirror-0-0.json","contact_source":"unavailable","contact":null}
```

Use a stable relative source identifier when sharing episode records. `success` is a boolean, and `score` is the native score normalized to [0, 1]. Omit outcomes from incomplete records. Contact measurements use `native` or `replay` with a boolean flag. Missing or inapplicable measurements use `unavailable` or `not_applicable` with a null flag.

Supply all paired episode slots for every selected policy and resolve replacement runs for each slot before aggregation:

```bash
python -m paper_repro.metrics episodes.jsonl --policy wall_oss
```

The paper's main table uses 480 episodes each for WALL-OSS, VPP2, Awomo-0.5, and Rex-M1 Preview, and 160 for GPT-6-Astra. The aggregator checks layout and seed coverage, computes task averages, and resamples matched layout clusters for intervals. The raw paper runs, checkpoints, and diagnostic runners are external dependencies. The [README results table](../README.md#benchmark-results) reports the paper's aggregate success rates.
