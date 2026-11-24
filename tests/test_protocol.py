import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from paper_repro.evaluate import CONFIG_DIR, case_context, evaluate_case, load_json
from paper_repro.metrics import aggregate
from paper_repro.scenes import corrected_dual_specs


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_json(CONFIG_DIR / "paper_main.json")
        self.rows = [
            dict(policy="astra", task=task, condition=condition, layout=layout,
                 seed=0, status="complete", placement_revision="paper", source="fixture",
                 score=1.0 if condition == "no_mirror" else 0.25,
                 success=condition == "no_mirror")
            for task in self.protocol["tasks"]
            for condition in self.protocol["conditions"]
            for layout in range(5)
        ]

    def test_macro_drop_and_layout_interval(self):
        result = aggregate(self.protocol, self.rows, ["astra"], replicates=64)["astra"]
        self.assertEqual(result["mean_success_drop_pp"], 100)
        self.assertEqual(result["mean_score_drop_points"], 75)
        self.assertEqual(result["success_drop_ci95_pp"], [100, 100])

    def test_contact_rate_counts_only_measured_episodes(self):
        dual = [row for row in self.rows if row["condition"] == "dual_mirror"]
        dual[0].update(contact=False, contact_source="native")
        dual[1].update(contact=True, contact_source="native")
        dual[2].update(contact=True, contact_source="replay")
        result = aggregate(self.protocol, self.rows, ["astra"], replicates=4)["astra"]
        contact = result["tasks"]["cover_blocks"]["dual_mirror"]["contact_by_source"]
        self.assertEqual(contact["native"]["episodes"], 2)
        self.assertEqual(contact["native"]["episode_rate_pct"], 50)
        self.assertEqual(contact["replay"]["episode_rate_pct"], 100)

    def test_incomplete_missing_and_duplicate_slots(self):
        with self.assertRaisesRegex(ValueError, "unmatched slots"):
            aggregate(self.protocol, self.rows[:-1], ["astra"], replicates=4)
        incomplete = dict(self.rows[-1], status="interrupted", score=None, success=None)
        with self.assertRaisesRegex(ValueError, "unmatched slots"):
            aggregate(self.protocol, self.rows[:-1] + [incomplete], ["astra"], replicates=4)
        with self.assertRaisesRegex(ValueError, "Duplicate episode"):
            aggregate(self.protocol, self.rows + [incomplete], ["astra"], replicates=4)

    def test_revised_geometry_cannot_enter_paper_metrics(self):
        self.rows[-1]["placement_revision"] = "independent_robot_object_normal_5cm_v2"
        with self.assertRaisesRegex(ValueError, "paper placement revision"):
            aggregate(self.protocol, self.rows, ["astra"], replicates=4)

    def test_corrected_geometry_preserves_inputs_and_supports_both_meshes(self):
        revision = load_json(CONFIG_DIR / "corrected_dual.json")
        robot = [[-0.3, 0.4, 0.5]]
        objects = [[0.5, 0.2, 0.6]]
        before = copy.deepcopy((robot, objects))
        left, right = corrected_dual_specs([0, 0, 0.4], [2, 1, 0.1], robot, objects, revision)
        self.assertEqual((robot, objects), before)
        self.assertEqual(left["seam"], right["seam"])
        self.assertAlmostEqual(sum(a * b for a, b in zip(left["normal"], right["normal"])), 0)
        self.assertAlmostEqual(left["endpoint"][0], -1)
        self.assertAlmostEqual(right["endpoint"][0], 1)
        for panel in (left, right):
            self.assertAlmostEqual(panel["clearance_m"], 0.05)

    def test_panel_uses_matching_geometry(self):
        args = argparse.Namespace(
            policy="wall_oss", task="cover_blocks", condition="dual_panel",
            layout=0, seed=0, corrected_dual=True,
        )
        control = case_context(args)
        args.condition = "dual_mirror"
        mirror = case_context(args)
        self.assertEqual(mirror["geometry"], control["geometry"])
        self.assertEqual(mirror["placement_revision"], control["placement_revision"])
        self.assertNotEqual(mirror["material"], control["material"])
        args.condition, args.policy = "dual_panel", "astra"
        with self.assertRaisesRegex(ValueError, "unavailable"):
            case_context(args)

    def test_native_runner_reports_completed_score(self):
        args = argparse.Namespace(
            policy="wall_oss", task="cover_blocks", condition="dual_mirror",
            layout=1, seed=2, corrected_dual=False,
        )
        case = case_context(args)
        runner = {
            "argv": ["native-eval", "{task}", "{layout}", "{seed}"],
            "identity_fields": {
                "task": ["task"], "layout": ["layout_id"],
                "seed": ["model_seed"], "condition": ["condition"],
            },
            "identity_values": {"condition": "double_mirror"},
            "completion": {"file": "exit.json", "field": ["returncode"], "values": [0]},
            "score_field": ["score"],
            "success_field": ["success"],
            "score_max": 100,
            "result": "result.json",
            "contact_field": ["collision_steps"],
            "contact_source": "native",
            "contact_threshold": 0,
        }
        # Use the approved project directory for the ephemeral runner fixture.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tests") as root:
            manifest = Path(root) / "runtime.json"
            manifest.write_text(json.dumps({"wall_oss": {"paper": {"dual_mirror": runner}}}))

            def write_result(argv, **kwargs):
                self.assertEqual(argv, ["native-eval", "cover_blocks", "1", "2"])
                directory = kwargs["cwd"]
                (directory / "result.json").write_text(json.dumps(dict(
                    task="cover_blocks", layout_id=1, model_seed=2,
                    condition="double_mirror", score=25, success=False, collision_steps=0,
                )))
                (directory / "exit.json").write_text('{"returncode": 0}')

            with patch("paper_repro.evaluate.subprocess.run", side_effect=write_result):
                record = evaluate_case(manifest, case)
                self.assertEqual(record["score"], 0.25)
                self.assertFalse(record["success"])
                self.assertIs(record["contact"], False)
                with self.assertRaisesRegex(ValueError, "already exists"):
                    evaluate_case(manifest, case)


if __name__ == "__main__":
    unittest.main()
