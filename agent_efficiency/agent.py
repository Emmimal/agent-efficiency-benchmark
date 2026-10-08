"""The simulated coding agent.

It follows a sensible task-solving policy (run tests -> read the failure ->
edit -> re-run -> finish) and deviates from it with profile-specific
probabilities. The profile numbers are HYPOTHETICAL behaviour classes, not
measurements of any real agent.

How the agent reacts to a harness is explicit and sweepable:
  * compliance   - probability it actually acts on a harness directive
  * plan_benefit - how much a forced plan phase lowers its wrong-edit rate
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .tasks import DECOYS, Edit, Task


@dataclass(frozen=True)
class Profile:
    wrong_file: float       # chance a fix attempt goes to a wrong place
    repeat_failure: float   # chance of re-running a failing command unchanged
    revert: float           # chance of reverting its last edit after a failure
    premature_stop: float   # chance of declaring "done" while tests still fail
    overwork: float         # chance of an unneeded edit after tests pass
    decoy_share: float = 0.5   # share of "wrong" edits that go to an unrelated file (rest: wrong fix in the right file)
    oscillate: float = 0.0     # chance of re-applying a just-reverted edit (held-out behaviour)
    rerun_pass: float = 0.0    # chance of re-running passing tests unchanged, up to 3x (held-out behaviour)
    core_thrash: float = 0.0   # chance of a pointless cosmetic edit in the correct file after a pass (held-out)


PROFILES: dict[str, Profile] = {
    "careful": Profile(0.05, 0.05, 0.02, 0.03, 0.05),
    "normal": Profile(0.15, 0.15, 0.08, 0.08, 0.15),
    "sloppy": Profile(0.30, 0.30, 0.20, 0.18, 0.30),
    "loop_prone": Profile(0.10, 0.55, 0.15, 0.05, 0.40),
}


# Held-out behaviours (see HELDOUT.md). No unrelated-file edits, no premature stopping.
HELDOUT_PROFILES: dict[str, Profile] = {
    "held_oscillate": Profile(0.35, 0.05, 0.0, 0.0, 0.0, decoy_share=0.0, oscillate=0.6),
    "held_rerun": Profile(0.05, 0.05, 0.0, 0.0, 0.0, decoy_share=0.0, rerun_pass=0.5),
    "held_core_thrash": Profile(0.05, 0.05, 0.0, 0.0, 0.0, decoy_share=0.0, core_thrash=0.6),
    "held_mixed": Profile(0.25, 0.10, 0.05, 0.0, 0.0, decoy_share=0.0, oscillate=0.4, rerun_pass=0.3, core_thrash=0.3),
}


def get_profile(name: str) -> Profile:
    return PROFILES[name] if name in PROFILES else HELDOUT_PROFILES[name]


@dataclass(frozen=True)
class Action:
    kind: str                      # run_tests | inspect | inspect_diff | edit | revert | plan | gate | finish
    path: str | None = None
    edit: Edit | None = None
    reason: str = ""


@dataclass(frozen=True)
class View:
    """What the agent can observe about the current repository state."""

    turn: int
    last_action: str | None
    ever_tested: bool
    known_exit: int | None     # test result for THIS exact state, if it was run before
    known_out: str | None      # hash of that test output
    applied: tuple[Edit, ...]  # edits currently applied, oldest first


class SimulatedAgent:
    def __init__(self, task: Task, profile: str, seed_key: str, compliance: float, plan_benefit: float):
        self.task = task
        self.p = get_profile(profile)
        # Separate streams so harness-related rolls never shift the main stream;
        # this keeps runs paired across harnesses for the same seed.
        self.rng = random.Random(f"agent|{seed_key}")
        self.crng = random.Random(f"comply|{seed_key}")
        self.compliance = compliance
        self.plan_benefit = plan_benefit
        self.plan_active = False
        self.force_correct = False
        self.cleanup_pending = False
        self.diagnosed_out: str | None = None
        self.overwork_bouts = 0
        self.last_reverted: Edit | None = None
        self.reruns = 0
        self.thrashed = False

    # ---- harness-facing hooks -------------------------------------------
    def accept_plan(self) -> None:
        self.plan_active = self.crng.random() < self.compliance

    def accept_review(self) -> None:
        if self.crng.random() < self.compliance:
            self.cleanup_pending = True

    def respond(self, v: View, directive: str) -> Action | None:
        """Adaptive-harness directive. Returns None when the agent ignores it."""
        if self.crng.random() >= self.compliance:
            return None
        if directive in ("diagnose", "change_strategy"):
            self.force_correct = True
            return Action("inspect", path=self.task.fix.path, reason=f"{directive}: re-read the code")
        if directive in ("inspect_diff", "justify", "verify"):
            self.cleanup_pending = True
            return Action("inspect_diff", reason=f"{directive}: review accumulated diff")
        return None

    # ---- decisions -------------------------------------------------------
    def decide(self, v: View) -> Action:
        if self.cleanup_pending:
            stray = [e for e in v.applied if e != self.task.fix]
            if stray:
                return Action("revert", edit=stray[-1], reason="cleanup of stray edit")
            self.cleanup_pending = False
        return self._policy(v)

    def _decoy(self, v: View) -> Edit | None:
        free = [d for d in DECOYS if d not in v.applied]
        return self.rng.choice(free) if free else None

    def _policy(self, v: View) -> Action:
        r, p, task = self.rng, self.p, self.task
        if not v.ever_tested:
            return Action("run_tests", reason="establish baseline")
        if v.known_exit is None:
            return Action("run_tests", reason="test the change")

        if v.known_exit == 0:
            if p.rerun_pass > 0 and self.reruns < 3 and r.random() < p.rerun_pass:
                self.reruns += 1
                return Action("run_tests", reason="re-run passing tests to be sure")
            if p.core_thrash > 0 and not self.thrashed and r.random() < p.core_thrash:
                self.thrashed = True
                return Action("edit", edit=task.cosmetic, path=task.cosmetic.path, reason="pointless cosmetic edit")
            if self.overwork_bouts < 3 and r.random() < p.overwork:
                decoy = self._decoy(v)
                if decoy is not None:
                    self.overwork_bouts += 1
                    return Action("edit", edit=decoy, path=decoy.path, reason="unneeded tidy-up")
            return Action("finish", reason="tests pass")

        # tests failing on a clean (already tested) state
        if v.last_action == "run_tests" and r.random() < p.repeat_failure:
            return Action("run_tests", reason="re-run unchanged, hoping for a different result")
        if r.random() < p.premature_stop:
            return Action("finish", reason="gives up too early")
        if v.known_out != self.diagnosed_out:
            self.diagnosed_out = v.known_out
            return Action("inspect", path=task.fix.path, reason="read the failure")
        if task.wrong_fix in v.applied:
            self.last_reverted = task.wrong_fix
            return Action("revert", edit=task.wrong_fix, reason="undo wrong fix")
        if v.applied and r.random() < p.revert:
            self.last_reverted = v.applied[-1]
            return Action("revert", edit=v.applied[-1], reason="reverts last change")
        return self._choose_edit(v)

    def _choose_edit(self, v: View) -> Action:
        r, task = self.rng, self.task
        if self.force_correct:
            self.force_correct = False
            return Action("edit", edit=task.fix, path=task.fix.path, reason="changed strategy: correct fix")
        if (self.p.oscillate > 0 and self.last_reverted is not None
                and self.last_reverted not in v.applied and r.random() < self.p.oscillate):
            e = self.last_reverted
            self.last_reverted = None
            return Action("edit", edit=e, path=e.path, reason="re-applies the edit it just reverted")
        wrong = self.p.wrong_file * ((1 - self.plan_benefit) if self.plan_active else 1.0)
        if r.random() < wrong:
            if r.random() < self.p.decoy_share:
                decoy = self._decoy(v)
                if decoy is not None:
                    return Action("edit", edit=decoy, path=decoy.path, reason="edits the wrong file")
            return Action("edit", edit=task.wrong_fix, path=task.wrong_fix.path, reason="plausible but wrong fix")
        return Action("edit", edit=task.fix, path=task.fix.path, reason="applies the fix")
