"""Session (executes actions against the real repo and records events) and
the three harnesses that sit between the agent and the repository."""
from __future__ import annotations

import time

from .agent import Action, SimulatedAgent, View
from .recorder import Event
from .repo import TEST_COMMAND, Repo, sha
from .tasks import Task


class Session:
    def __init__(self, run_id: str, task: Task, repo: Repo, agent: SimulatedAgent, max_turns: int = 40):
        self.run_id = run_id
        self.task = task
        self.repo = repo
        self.agent = agent
        self.max_turns = max_turns
        self.events: list[Event] = []
        self.turn = 0
        self.finished = False
        self.ever_tested = False
        self.tested: dict[str, tuple[int, str]] = {}   # state hash -> (exit, output hash)
        self.applied: list = []
        self.last_action: str | None = None
        self.relevant = repo.relevant_files()          # inferred from the tests' imports
        self.t0 = time.perf_counter()

    # ---- observation -----------------------------------------------------
    def view(self) -> View:
        known = self.tested.get(self.repo.state_hash())
        return View(
            turn=self.turn,
            last_action=self.last_action,
            ever_tested=self.ever_tested,
            known_exit=known[0] if known else None,
            known_out=known[1] if known else None,
            applied=tuple(self.applied),
        )

    def agent_step(self) -> tuple[Action, str]:
        """Ask the agent for its next action. Cleanup reverts that were
        requested by a harness are attributed to the harness."""
        cleanup = self.agent.cleanup_pending
        action = self.agent.decide(self.view())
        phase = "harness:cleanup" if (cleanup and action.kind == "revert") else "agent"
        return action, phase

    # ---- execution -------------------------------------------------------
    def execute(self, a: Action, phase: str = "agent") -> Event:
        self.turn += 1
        before = self.repo.state_hash()
        target = command = out_hash = edit_key = None
        exit_code = None
        added = removed = 0

        if a.kind == "run_tests":
            command = TEST_COMMAND
            exit_code, out_hash = self.repo.run_tests()
            self.tested[before] = (exit_code, out_hash)
            self.ever_tested = True
        elif a.kind == "inspect":
            target, command = a.path, f"cat {a.path}"
            out_hash = sha(self.repo.read(a.path))
        elif a.kind == "inspect_diff":
            command = "git diff"
            out_hash = sha(self.repo.diff_text())
        elif a.kind == "edit":
            target, command, edit_key = a.edit.path, f"edit {a.edit.path}", a.edit.key
            res = self.repo.apply(a.edit)
            if res.changed:
                self.applied.append(a.edit)
                added, removed = res.added, res.removed
        elif a.kind == "revert":
            target, command, edit_key = a.edit.path, f"revert {a.edit.path}", a.edit.key
            res = self.repo.apply(a.edit.reversed())
            if res.changed:
                if a.edit in self.applied:
                    self.applied.remove(a.edit)
                added, removed = res.added, res.removed
        elif a.kind == "finish":
            self.finished = True
        # plan / gate: no repository effect

        event = Event(
            run_id=self.run_id, turn=self.turn, phase=phase, action=a.kind,
            target=target, command=command, exit_code=exit_code, output_hash=out_hash,
            state_before=before, state_after=self.repo.state_hash(),
            diff_added=added, diff_removed=removed, edit_key=edit_key,
            reason=a.reason, timestamp=time.perf_counter() - self.t0,
        )
        self.events.append(event)
        self.last_action = a.kind
        return event


class Harness:
    name = "base"

    def run(self, s: Session) -> str:
        """Drive the session; return the end reason."""
        raise NotImplementedError

    @staticmethod
    def _end(s: Session) -> str:
        return "finished" if s.finished else "max_turns"


class BasicHarness(Harness):
    """Task -> agent -> tools -> done. No intervention."""

    name = "basic"

    def run(self, s: Session) -> str:
        while not s.finished and s.turn < s.max_turns:
            action, phase = s.agent_step()
            s.execute(action, phase)
        return self._end(s)


class StructuredHarness(Harness):
    """PLAN -> IMPLEMENT -> TEST -> REVIEW -> DONE, regardless of how the run is going."""

    name = "structured"

    def run(self, s: Session) -> str:
        s.execute(Action("plan", reason="PLAN phase"), "harness:plan")
        s.agent.accept_plan()
        reviewed = False
        while not s.finished and s.turn < s.max_turns:
            action, phase = s.agent_step()
            if action.kind != "finish":
                s.execute(action, phase)
                continue
            if s.view().known_exit != 0:                       # TEST gate
                s.execute(Action("gate", reason="cannot finish: tests not passing"), "harness:gate")
                continue
            if not reviewed:                                   # REVIEW phase, always, once
                reviewed = True
                s.execute(Action("inspect_diff", reason="REVIEW phase"), "harness:review")
                s.agent.accept_review()
                continue
            s.execute(action, phase)
        return self._end(s)


ALL_RULES = ("R1", "R2", "R3", "R4", "R5")


class AdaptiveHarness(Harness):
    """No fixed sequence. Watches the trajectory and intervenes on evidence of waste:

      R1 same command failed twice, no state change        -> diagnose before editing again
      R2 same file modified twice, or two or more reverts  -> inspect accumulated diff
      R3 3 turns with no state change                      -> change strategy
      R4 tests pass after a messy run                      -> verify (review diff)
      R5 edit to a file the tests do not import            -> justify / undo
      Gate: cannot finish while tests fail.

    `rules` and `gate` exist for ablations; the defaults are the full harness.
    """

    COOLDOWN = 3

    def __init__(self, name: str = "adaptive", rules=ALL_RULES, gate: bool = True):
        self.name = name
        self.rules = frozenset(rules)
        self.gate = gate

    def run(self, s: Session) -> str:
        last_fire: dict[str, int] = {}
        verified: set[str] = set()
        while not s.finished and s.turn < s.max_turns:
            fired = self._check(s, last_fire, verified)
            if fired:
                rule, directive = fired
                last_fire[rule] = s.turn
                action = s.agent.respond(s.view(), directive)
                if action is not None:
                    s.execute(action, f"harness:{rule}")
                    continue
            action, phase = s.agent_step()
            if self.gate and action.kind == "finish" and s.view().known_exit != 0:
                s.execute(Action("gate", reason="cannot finish: tests not passing"), "harness:gate")
                continue
            s.execute(action, phase)
        return self._end(s)

    def _check(self, s: Session, last_fire: dict[str, int], verified: set[str]):
        ev, on = s.events, self.rules
        if not ev:
            return None
        last = ev[-1]

        def ready(rule: str) -> bool:
            return s.turn - last_fire.get(rule, -99) >= self.COOLDOWN

        mods = [e for e in ev if e.action in ("edit", "revert") and e.state_changed]

        if "R1" in on and len(ev) >= 2 and ready("R1"):
            a, b = ev[-2], ev[-1]
            if a.action == b.action == "run_tests" and a.state_before == b.state_before and b.exit_code not in (0, None):
                return "R1", "diagnose"
        if "R3" in on and len(ev) >= 3 and ready("R3") and all(not e.state_changed and e.action != "finish" for e in ev[-3:]):
            return "R3", "change_strategy"
        if ("R5" in on and last.action == "edit" and last.state_changed and last.target not in s.relevant
                and any(x.key == last.edit_key for x in s.applied) and ready("R5")):
            return "R5", "justify"
        if "R2" in on and mods and last is mods[-1] and ready("R2"):
            same_file = sum(1 for e in mods if e.target == last.target)
            reverts = sum(1 for e in mods if e.action == "revert")
            if same_file >= 2 or reverts >= 2:
                return "R2", "inspect_diff"
        if "R4" in on:
            v = s.view()
            state = s.repo.state_hash()
            if v.known_exit == 0 and state not in verified and len(verified) < 2 and ready("R4"):
                stray = any(x != s.task.fix for x in s.applied)
                reverts = sum(1 for e in mods if e.action == "revert")
                if stray or reverts >= 1:
                    verified.add(state)
                    return "R4", "verify"
        return None


def _adaptive(name: str, rules=ALL_RULES, gate: bool = True):
    return lambda: AdaptiveHarness(name, rules, gate)


HARNESSES = {
    "basic": BasicHarness,
    "structured": StructuredHarness,
    "adaptive": _adaptive("adaptive"),
    # ablations (exploratory: designed after seeing the first results)
    "adaptive-gate-only": _adaptive("adaptive-gate-only", rules=(), gate=True),
    "adaptive-rules-only": _adaptive("adaptive-rules-only", gate=False),
    **{f"adaptive-no-{r}": _adaptive(f"adaptive-no-{r}", rules=[x for x in ALL_RULES if x != r])
       for r in ALL_RULES},
}
MAIN_HARNESSES = ("basic", "structured", "adaptive")
ABLATION_HARNESSES = ("basic", "adaptive", "adaptive-gate-only", "adaptive-rules-only",
                      *[f"adaptive-no-{r}" for r in ALL_RULES])
