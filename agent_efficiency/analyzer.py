"""Efficiency analyzer: derives every waste metric from raw trajectory events.

Definitions (all computed here, none stored in the trajectory):

  wasted turn  = an agent-phase turn with no useful state transition AND no new
                 diagnostic information:
      run_tests     the same command already ran on the identical state, or the
                    output was already seen and no relevant file changed since
                    the previous run
      inspect(_diff) the identical output was already seen in this run
      edit          no state change, an edit to a file the tests do not depend
                    on, or an edit that is later reverted
      revert        only when it changes nothing (reverting is recovery, not waste)
  harness turn = any turn the harness caused (plan, review, gate, directives,
                 cleanup). Reported separately; not counted as agent waste.
  repeated command = a read/test command re-run on an identical repo state.
  final diff   = lines added + removed between the initial and final repo.
  total churn  = lines added + removed summed over every edit and revert.
  churn ratio  = total churn / final diff (successful runs only).
"""
from __future__ import annotations

from .recorder import Trajectory

READ_ACTIONS = ("run_tests", "inspect", "inspect_diff")


def analyze(traj: Trajectory, relevant: set[str], annotate: list | None = None,
            ref_diff: int | None = None) -> dict:
    """Return metrics. If `annotate` is a list, per-event flag sets are appended to it."""
    ev, meta = traj.events, traj.meta

    # pair every revert with the most recent un-reverted matching edit
    open_edits: dict[str, list[int]] = {}
    reverted_idx: set[int] = set()
    for i, e in enumerate(ev):
        if not e.state_changed:
            continue
        if e.action == "edit":
            open_edits.setdefault(e.edit_key, []).append(i)
        elif e.action == "revert" and open_edits.get(e.edit_key):
            reverted_idx.add(open_edits[e.edit_key].pop())

    seen_cmd_state: set[tuple] = set()
    seen_info: set[tuple] = set()
    seen_test_out: set[str] = set()
    relevant_dirty = False
    wasted = repeated = failed_runs = unrelated_edits = recovery = 0
    files_touched: set[str] = set()

    for i, e in enumerate(ev):
        agent_phase = e.phase == "agent"
        is_waste = False
        is_repeat = False

        if e.action in READ_ACTIONS:
            key = (e.action, e.target, e.state_before)
            is_repeat = key in seen_cmd_state
            repeated += is_repeat
            seen_cmd_state.add(key)

        if e.action == "run_tests":
            if e.exit_code != 0:
                failed_runs += 1
            no_new_info = e.output_hash in seen_test_out and not relevant_dirty
            is_waste = is_repeat or no_new_info
            seen_test_out.add(e.output_hash)
            relevant_dirty = False
        elif e.action in ("inspect", "inspect_diff"):
            info = (e.action, e.target, e.output_hash)
            is_waste = info in seen_info
            seen_info.add(info)
        elif e.action == "edit":
            if e.state_changed:
                files_touched.add(e.target)
                if e.target not in relevant:
                    unrelated_edits += 1
            is_waste = (not e.state_changed) or (e.target not in relevant) or (i in reverted_idx)
        elif e.action == "revert":
            if e.state_changed:
                recovery += 1
                files_touched.add(e.target)
            else:
                is_waste = True

        if e.state_changed and e.action in ("edit", "revert") and e.target in relevant:
            relevant_dirty = True
        if agent_phase and is_waste:
            wasted += 1
        if annotate is not None:
            flags = set()
            if agent_phase and is_waste:
                flags.add("WASTED")
            if is_repeat:
                flags.add("repeat")
            if i in reverted_idx:
                flags.add("reverted-later")
            if e.action == "edit" and e.state_changed and e.target not in relevant:
                flags.add("unrelated-file")
            annotate.append(flags)

    total_churn = sum(e.diff_added + e.diff_removed for e in ev)
    final_diff = meta.final_added + meta.final_removed
    harness_turns = sum(1 for e in ev if e.phase.startswith("harness:"))
    turns = len(ev)
    return {
        "success": int(meta.success),
        "turns": turns,
        "wasted_turns": wasted,
        "wasted_share": wasted / turns if turns else 0.0,
        "harness_turns": harness_turns,
        "failed_runs": failed_runs,
        "repeated_commands": repeated,
        "reverted_edits": len(reverted_idx),
        "unrelated_edits": unrelated_edits,
        "recovery_turns": recovery,
        "files_touched": len(files_touched),
        "final_diff": final_diff,
        "total_churn": total_churn,
        "churn_ratio": (total_churn / final_diff) if (meta.success and final_diff > 0) else None,
        # lines in the final patch beyond the reference fix (successful runs only)
        "extra_diff_lines": max(0, final_diff - ref_diff) if (meta.success and ref_diff is not None) else None,
    }
