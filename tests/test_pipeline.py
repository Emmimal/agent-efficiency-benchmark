"""Sanity tests for the benchmark itself. Run:  python -m unittest discover -s tests -t ."""
import tempfile
import unittest

from agent_efficiency.agent import Action
from agent_efficiency.analyzer import analyze
from agent_efficiency.experiment import run_one
from agent_efficiency.harness import Session
from agent_efficiency.recorder import RunMeta, Trajectory
from agent_efficiency.repo import Repo
from agent_efficiency.tasks import DECOYS, TASKS, TASKS_BY_NAME


def fresh(task, cache=False):
    tmp = tempfile.TemporaryDirectory()
    return tmp, Repo(task, tmp.name, use_cache=cache)


class TaskTests(unittest.TestCase):
    def test_every_task_is_well_formed(self):
        for task in TASKS:
            with self.subTest(task=task.name):
                tmp, repo = fresh(task)
                with tmp:
                    initial = repo.state_hash()
                    self.assertNotEqual(repo.run_tests()[0], 0, "bug must make tests fail")
                    self.assertTrue(repo.apply(task.fix).changed)
                    self.assertEqual(repo.run_tests()[0], 0, "reference fix must pass")
                    self.assertTrue(repo.apply(task.fix.reversed()).changed)
                    self.assertEqual(repo.state_hash(), initial, "revert restores state")
                    self.assertTrue(repo.apply(task.wrong_fix).changed)
                    self.assertNotEqual(repo.run_tests()[0], 0, "wrong fix must still fail")

    def test_decoys_never_change_the_outcome(self):
        for task in TASKS:
            with self.subTest(task=task.name):
                tmp, repo = fresh(task)
                with tmp:
                    for d in DECOYS:
                        self.assertTrue(repo.apply(d).changed)
                    self.assertNotEqual(repo.run_tests()[0], 0)
                    repo.apply(task.fix)
                    self.assertEqual(repo.run_tests()[0], 0)

    def test_cache_matches_real_execution(self):
        task = TASKS[0]
        a_tmp, a = fresh(task, cache=True)
        b_tmp, b = fresh(task, cache=False)
        with a_tmp, b_tmp:
            self.assertEqual(a.run_tests(), b.run_tests())


class AnalyzerTests(unittest.TestCase):
    def test_known_trajectory(self):
        task = TASKS_BY_NAME["off_by_one_range"]
        tmp, repo = fresh(task)
        with tmp:
            from agent_efficiency.agent import SimulatedAgent
            s = Session("t", task, repo, SimulatedAgent(task, "careful", "k", 0.5, 0.0))
            script = [
                Action("run_tests"),
                Action("run_tests"),                                   # repeated, wasted
                Action("inspect", path=task.fix.path),
                Action("edit", edit=task.wrong_fix),                   # later reverted, wasted
                Action("run_tests"),                                   # new failure output, informative
                Action("revert", edit=task.wrong_fix),
                Action("edit", edit=task.fix),
                Action("run_tests"),
                Action("finish"),
            ]
            for a in script:
                s.execute(a)
            meta = RunMeta("t", task.name, "basic", "careful", 0, 0.5, 0.0, success=True)
            meta.final_added, meta.final_removed, _ = repo.final_diff()
            m = analyze(Trajectory(meta, s.events), {task.fix.path})
        self.assertEqual(m["turns"], 9)
        self.assertEqual(m["failed_runs"], 3)
        self.assertEqual(m["repeated_commands"], 1)
        self.assertEqual(m["wasted_turns"], 2)
        self.assertEqual(m["reverted_edits"], 1)
        self.assertEqual(m["recovery_turns"], 1)
        self.assertEqual(m["final_diff"], 2)
        self.assertEqual(m["total_churn"], 6)
        self.assertAlmostEqual(m["churn_ratio"], 3.0)


class RunTests(unittest.TestCase):
    def test_runs_are_deterministic(self):
        task = TASKS[2]
        a, _ = run_one(task, "adaptive", "sloppy", 7, 0.5, 0.0)
        b, _ = run_one(task, "adaptive", "sloppy", 7, 0.5, 0.0)
        strip = lambda t: [(e.action, e.phase, e.state_after, e.exit_code) for e in t.events]
        self.assertEqual(strip(a), strip(b))

    def test_careful_basic_is_the_clean_baseline(self):
        for task in TASKS:
            traj, m = run_one(task, "basic", "careful", 0, 0.5, 0.0)
            if m["success"]:
                self.assertLessEqual(m["wasted_turns"], 3)

    def test_gate_stops_premature_finish(self):
        # with a very high premature-stop rate, adaptive/structured must beat basic on success
        import agent_efficiency.agent as ag
        ag.PROFILES["_quitter"] = ag.Profile(0.0, 0.0, 0.0, 0.9, 0.0)
        try:
            ok = {h: sum(run_one(t, h, "_quitter", s, 1.0, 0.0)[1]["success"] for t in TASKS for s in range(5))
                  for h in ("basic", "structured", "adaptive")}
        finally:
            del ag.PROFILES["_quitter"]
        self.assertGreater(ok["structured"], ok["basic"])
        self.assertGreater(ok["adaptive"], ok["basic"])


class AblationAndViewerTests(unittest.TestCase):
    @staticmethod
    def shape(traj):
        return [(e.phase, e.action, e.state_after, e.exit_code) for e in traj.events]

    def test_gate_only_equals_adaptive_with_zero_compliance(self):
        # at compliance 0 the rules fire but are ignored, so only the finish gate acts
        for task in TASKS[:4]:
            for seed in range(6):
                a, _ = run_one(task, "adaptive", "sloppy", seed, 0.0, 0.0)
                b, _ = run_one(task, "adaptive-gate-only", "sloppy", seed, 1.0, 0.0)
                self.assertEqual(self.shape(a), self.shape(b))

    def test_rules_only_equals_basic_with_zero_compliance(self):
        for task in TASKS[:4]:
            for seed in range(6):
                a, _ = run_one(task, "basic", "loop_prone", seed, 0.0, 0.0)
                b, _ = run_one(task, "adaptive-rules-only", "loop_prone", seed, 0.0, 0.0)
                self.assertEqual(self.shape(a), self.shape(b))

    def test_annotations_agree_with_metrics(self):
        from agent_efficiency.harness import HARNESSES
        for h in ("basic", "structured", "adaptive"):
            cap = {}
            traj, m = run_one(TASKS[3], h, "sloppy", 4, 0.5, 0.0, capture=cap)
            self.assertEqual(len(cap["flags"]), len(traj.events))
            self.assertEqual(sum("WASTED" in f for f in cap["flags"]), m["wasted_turns"])

    def test_every_registered_harness_runs(self):
        from agent_efficiency.harness import HARNESSES
        for h in HARNESSES:
            _, m = run_one(TASKS[0], h, "normal", 1, 0.5, 0.0)
            self.assertIn(m["success"], (0, 1))

    def test_viewer_renders(self):
        from agent_efficiency.show import render
        text = render(TASKS[0], "adaptive", "sloppy", 12, 0.5, 0.0)
        self.assertIn("outcome:", text)
        self.assertIn("final diff", text)


class HeldOutTests(unittest.TestCase):
    def test_reference_diff_matches_applied_fix(self):
        for task in TASKS:
            tmp, repo = fresh(task)
            with tmp:
                repo.apply(task.fix)
                a, r, _ = repo.final_diff()
                self.assertEqual(a + r, task.reference_diff(), task.name)

    def test_cosmetic_edit_is_harmless_and_reversible(self):
        for task in TASKS:
            with self.subTest(task=task.name):
                tmp, repo = fresh(task)
                with tmp:
                    repo.apply(task.fix)
                    self.assertTrue(repo.apply(task.cosmetic).changed)
                    self.assertEqual(repo.run_tests()[0], 0)
                    self.assertTrue(repo.apply(task.cosmetic.reversed()).changed)

    def test_heldout_profiles_never_touch_unrelated_files(self):
        from agent_efficiency.agent import HELDOUT_PROFILES
        for profile in HELDOUT_PROFILES:
            for h in ("basic", "structured", "adaptive"):
                for task in TASKS[:5]:
                    for seed in range(8):
                        _, m = run_one(task, h, profile, seed, 1.0, 0.0)
                        self.assertEqual(m["unrelated_edits"], 0, (profile, h, task.name, seed))

    def test_heldout_behaviours_actually_occur(self):
        from agent_efficiency.agent import HELDOUT_PROFILES
        def total(profile, key, h="basic"):
            return sum(run_one(t, h, profile, s, 0.5, 0.0)[1][key] for t in TASKS for s in range(10))
        self.assertGreater(total("held_oscillate", "reverted_edits"), 0)
        self.assertGreater(total("held_rerun", "repeated_commands"), 0)
        self.assertGreater(total("held_core_thrash", "extra_diff_lines") or 0, 0)

    def test_original_profiles_unchanged_by_new_fields(self):
        # new behaviours are guarded: a fixed run must keep its exact event sequence
        traj, _ = run_one(TASKS[2], "basic", "sloppy", 3, 0.5, 0.0)
        again, _ = run_one(TASKS[2], "basic", "sloppy", 3, 0.5, 0.0)
        self.assertEqual([e.action for e in traj.events], [e.action for e in again.events])


if __name__ == "__main__":
    unittest.main()
