"""Print the same task / profile / seed through each harness, turn by turn,
with the real final diff. Use it to pick illustrative trajectories for the article.

    python -m agent_efficiency.show --task off_by_one_range --profile sloppy --seed 3
    python -m agent_efficiency.show --profile sloppy --pick adaptive-wins
    python -m agent_efficiency.show --profile loop_prone --pick adaptive-loses

--pick scans tasks and seeds in a fixed order and takes the FIRST match, so the
choice is reproducible. A picked trajectory is an illustration, not a typical run.
"""
from __future__ import annotations

import argparse

from .agent import HELDOUT_PROFILES, PROFILES
from .experiment import run_one
from .harness import HARNESSES, MAIN_HARNESSES
from .tasks import TASKS, TASKS_BY_NAME


def _result(e) -> str:
    if e.action == "run_tests":
        return "PASS" if e.exit_code == 0 else f"FAIL#{e.output_hash[:4]}"
    if e.action in ("edit", "revert"):
        return ("applied" if e.action == "edit" else "undone") if e.state_changed else "no-op"
    if e.action in ("inspect", "inspect_diff"):
        return "read"
    return "done" if e.action == "finish" else "-"


def render(task, harness, profile, seed, compliance, plan_benefit) -> str:
    cap: dict = {}
    traj, m = run_one(task, harness, profile, seed, compliance, plan_benefit, capture=cap)
    lines = [
        f"--- {harness.upper()} | task={task.name} profile={profile} seed={seed} "
        f"compliance={compliance} plan_benefit={plan_benefit}",
        f"{'#':>2} {'phase':<16}{'action':<13}{'target':<14}{'result':<11}{'+/-':<7}{'flags':<40}reason",
    ]
    for e, flags in zip(traj.events, cap["flags"]):
        delta = f"+{e.diff_added}/-{e.diff_removed}" if e.diff_added or e.diff_removed else ""
        target = (e.target or "").split("/")[-1]
        lines.append(f"{e.turn:>2} {e.phase:<16}{e.action:<13}{target:<14}{_result(e):<11}{delta:<7}"
                     f"{','.join(sorted(flags)):<40}{e.reason}")
    lines.append(
        f"   outcome: {'SOLVED' if m['success'] else 'FAILED'} | turns={m['turns']} wasted={m['wasted_turns']} "
        f"harness_turns={m['harness_turns']} failed_runs={m['failed_runs']} reverted={m['reverted_edits']} "
        f"final_diff={m['final_diff']} total_churn={m['total_churn']}")
    lines.append("   final diff:" + ("" if cap["diff"] else " (empty)"))
    lines.extend("     " + ln for ln in cap["diff"].splitlines())
    return "\n".join(lines)


def _metrics(task, harness, profile, seed, compliance, plan_benefit):
    return run_one(task, harness, profile, seed, compliance, plan_benefit)[1]


def pick(profile, mode, compliance, plan_benefit, tasks, max_seed=200):
    for task in tasks:
        for seed in range(max_seed):
            b = _metrics(task, "basic", profile, seed, compliance, plan_benefit)
            a = _metrics(task, "adaptive", profile, seed, compliance, plan_benefit)
            if not (b["success"] and a["success"]):
                continue
            if mode == "adaptive-wins" and b["wasted_turns"] - a["wasted_turns"] >= 2:
                return task, seed
            if mode == "adaptive-loses" and a["turns"] - b["turns"] >= 3:
                return task, seed
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Show trajectories for one task/profile/seed across harnesses.")
    ap.add_argument("--task", choices=list(TASKS_BY_NAME))
    ap.add_argument("--profile", default="sloppy", choices=[*PROFILES, *HELDOUT_PROFILES])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--compliance", type=float, default=0.5)
    ap.add_argument("--plan-benefit", type=float, default=0.0)
    ap.add_argument("--harnesses", nargs="+", default=list(MAIN_HARNESSES), choices=list(HARNESSES))
    ap.add_argument("--pick", choices=["adaptive-wins", "adaptive-loses"],
                    help="first (task, seed) where both basic and adaptive solve it and the criterion holds: "
                         "wins = adaptive wasted >=2 fewer turns; loses = adaptive used >=3 more total turns")
    args = ap.parse_args(argv)

    task = TASKS_BY_NAME[args.task] if args.task else None
    seed = args.seed
    if args.pick:
        found_task, found_seed = pick(args.profile, args.pick, args.compliance, args.plan_benefit,
                                      [task] if task else list(TASKS))
        if found_task is None:
            raise SystemExit(f"No match for {args.pick} with profile={args.profile}.")
        task, seed = found_task, found_seed
        print(f"[selected by rule '{args.pick}': first match in a fixed scan. "
              f"An illustration, not a typical run.]\n")
    if task is None:
        task = TASKS[0]
    for h in args.harnesses:
        print(render(task, h, args.profile, seed, args.compliance, args.plan_benefit))
        print()


if __name__ == "__main__":
    main()
