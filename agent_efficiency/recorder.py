"""Trajectory recorder: raw, immutable facts only.

Flags such as "repeated" or "wasted" are NOT stored here. They are derived by
analyzer.py, so waste definitions can change without re-running anything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Event:
    run_id: str
    turn: int
    phase: str                 # "agent" or "harness:<reason>"
    action: str                # run_tests | inspect | inspect_diff | edit | revert | plan | gate | finish
    target: str | None
    command: str | None
    exit_code: int | None
    output_hash: str | None
    state_before: str
    state_after: str
    diff_added: int
    diff_removed: int
    edit_key: str | None
    reason: str
    timestamp: float           # seconds since run start

    @property
    def state_changed(self) -> bool:
        return self.state_before != self.state_after


@dataclass
class RunMeta:
    run_id: str
    task: str
    harness: str
    profile: str
    seed: int
    compliance: float
    plan_benefit: float
    success: bool = False
    end_reason: str = ""
    total_turns: int = 0
    final_added: int = 0
    final_removed: int = 0
    final_files: list[str] = field(default_factory=list)
    wall_time: float = 0.0


@dataclass
class Trajectory:
    meta: RunMeta
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"meta": asdict(self.meta), "events": [asdict(e) for e in self.events]}
