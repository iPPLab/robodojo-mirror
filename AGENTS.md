# RoboDojo-Mirror Agent Guide

Start with the [README usage instructions](README.md#usage). RoboDojo-Mirror is a scene adapter for an existing RoboDojo evaluation environment. Use the native RoboDojo evaluator, its task assets and layouts, and your policy's upstream adapter and checkpoint.

## Check the setup

Run these commands from the repository root. Set `ROBODOJO_ROOT` to your RoboDojo checkout, as shown in the README.

```bash
python -B tests/smoke_interfaces.py
PYTHONPATH=src python -B -m robodojo_mirror check-source --robodojo-root "$ROBODOJO_ROOT"
PYTHONPATH=src python -B -m robodojo_mirror list-tasks --robodojo-root "$ROBODOJO_ROOT"
```

These are CPU checks. The interface test uses a fake environment, and the source check inspects evaluator methods. A closed-loop check requires the simulator and a live policy service.

## Run a matched evaluation

- The scored conditions are `no_mirror`, `single_mirror`, `dual_mirror`, and `mirror_tabletop`. Use `single_panel` and `dual_panel` for optional diagnostic comparisons. The [scene configuration](src/robodojo_mirror/config.py) defines the condition identifiers.
- Start with the [policy adapter table](README.md#policy-adapters). Use the selected policy's upstream action space, checkpoint or service, and launch instructions. Record the adapter and model versions separately from the scene package.
- Follow the [matched-pair example](README.md#run-a-matched-pair) for a one-episode WALL-OSS check in `no_mirror` and `dual_mirror`. Run both conditions with the same task, layout, policy checkpoint, and policy seed. Use a fresh output directory for each condition.
- In the example evaluator, `--seed` selects the layout library. Confirm the actual `layout_id` and reset the policy seed separately through the policy service. Record both seeds and the layout ID.
- Check each native `_result.json` for the requested layout and one scored episode. Report completion, task success, and native score separately. A task failure with a native score is a completed evaluation. Record missing results as incomplete.

WALL-OSS was verified in a prepared RoboDojo environment. VPP2, Awomo-0.5, Rex-M1 Preview, and GPT-6-Astra need separate closed-loop verification with this package. A fresh public checkout has yet to be verified end to end. Record the RoboDojo revision and policy checkpoint or served model used in any new verification.
