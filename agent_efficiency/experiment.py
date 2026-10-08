"""Run the experiment grid:  profiles x harnesses x tasks x seeds
(x compliance x plan_benefit when sweeping).

    python -m agent_efficiency --seeds 20
    python -m agent_efficiency --seeds 50 --sweep --out results
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from .agent import HELDOUT_PROFILES, PROFILES, SimulatedAgent
from .analyzer import analyze
from .harness import ABLATION_HARNESSES, HARNESSES, MAIN_HARNESSES, Session
from .recorder import RunMeta, Trajectory
from .repo import Repo
from .tasks import TASKS, TASKS_BY_NAME

METRICS = [
    "success", "turns", "wasted_turns", "wasted_share", "harness_turns", "failed_runs",
    "repeated_commands", "reverted_edits", "unrelated_edits", "recovery_turns",
    "files_touched", "final_diff", "total_churn", "churn_ratio", "extra_diff_lines",
]


def run_one(task, harness: str, profile: str, seed: int, compliance: float,
            plan_benefit: float, max_turns: int = 40, use_cache: bool = True,
            capture: dict | None = None):
    seed_key = f"{profile}|{task.name}|{seed}"       # same for every harness -> paired runs
    run_id = f"{harness}|{profile}|{task.name}|{seed}|c{compliance}|p{plan_benefit}"
    meta = RunMeta(run_id, task.name, harness, profile, seed, compliance, plan_benefit)
    with tempfile.TemporaryDirectory(prefix="aeb_") as tmp:
        repo = Repo(task, tmp, use_cache=use_cache)
        agent = SimulatedAgent(task, profile, seed_key, compliance, plan_benefit)
        session = Session(run_id, task, repo, agent, max_turns)
        meta.end_reason = HARNESSES[harness]().run(session)
        # hidden ground-truth check (not part of the trajectory)
        meta.success = repo.run_tests()[0] == 0
        meta.final_added, meta.final_removed, meta.final_files = repo.final_diff()
        meta.total_turns = session.turn
        meta.wall_time = time.perf_counter() - session.t0
        traj = Trajectory(meta, session.events)
        annotate = [] if capture is not None else None
        metrics = analyze(traj, {task.fix.path}, annotate, ref_diff=task.reference_diff())
        if capture is not None:
            capture["diff"] = repo.diff_text()
            capture["flags"] = annotate
        return traj, metrics


def mean_ci(values):
    xs = [v for v in values if v is not None]
    if not xs:
        return float("nan"), 0.0
    m = statistics.fmean(xs)
    ci = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
    return m, ci


def summarize(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["compliance"], r["plan_benefit"], r["profile"], r["harness"])].append(r)
    out = []
    for (c, pb, profile, harness), rs in groups.items():
        row = {"compliance": c, "plan_benefit": pb, "profile": profile, "harness": harness, "runs": len(rs)}
        for m in METRICS:
            mean, ci = mean_ci([r[m] for r in rs])
            row[m], row[m + "_ci95"] = mean, ci
        out.append(row)
    return out


def paired_deltas(rows):
    """Mean (harness - basic) over identical (profile, task, seed) runs."""
    idx = {(r["compliance"], r["plan_benefit"], r["profile"], r["task"], r["seed"], r["harness"]): r for r in rows}
    acc = defaultdict(lambda: defaultdict(list))
    for (c, pb, profile, task, seed, harness), r in idx.items():
        if harness == "basic":
            continue
        base = idx.get((c, pb, profile, task, seed, "basic"))
        if base is None:
            continue
        for m in ("success", "turns", "wasted_turns", "harness_turns", "total_churn"):
            acc[(c, pb, profile, harness)][m].append(r[m] - base[m])
        if r["success"] and base["success"]:   # fair cost comparison: both runs solved the task
            for m in ("turns", "wasted_turns", "harness_turns", "final_diff", "total_churn", "churn_ratio",
                      "extra_diff_lines"):
                acc[(c, pb, profile, harness)][m + "_ok"].append(r[m] - base[m])
    return acc


def print_tables(summary, deltas):
    present = {s["harness"] for s in summary}
    present_p = {s["profile"] for s in summary}
    order_p = [p for p in (*PROFILES, *HELDOUT_PROFILES) if p in present_p]
    order_h = [h for h in HARNESSES if h in present]
    combos = sorted({(s["compliance"], s["plan_benefit"]) for s in summary})
    for c, pb in combos:
        print(f"\n=== compliance={c}  plan_benefit={pb} ===")
        print(f"{'profile':<17}{'harness':<20}{'n':>5}{'succ%':>7}{'turns':>14}{'wasted':>14}"
              f"{'harness':>9}{'failed':>8}{'reverts':>9}{'churn x':>9}")
        for p in order_p:
            for h in order_h:
                s = next((x for x in summary if (x["compliance"], x["plan_benefit"], x["profile"], x["harness"]) == (c, pb, p, h)), None)
                if not s:
                    continue
                print(f"{p:<17}{h:<20}{s['runs']:>5}{100*s['success']:>6.1f}%"
                      f"{s['turns']:>8.2f}±{s['turns_ci95']:<4.2f}{s['wasted_turns']:>8.2f}±{s['wasted_turns_ci95']:<4.2f}"
                      f"{s['harness_turns']:>9.2f}{s['failed_runs']:>8.2f}{s['reverted_edits']:>9.2f}"
                      f"{s['churn_ratio']:>9.2f}")
        print("  paired difference vs basic (same profile/task/seed; mean ± 95% CI)")
        print("  'both ok' columns use only seeds where basic AND the harness solved the task,")
        print("  because basic often ends early by quitting, which flatters its raw turn counts.")
        print(f"  {'profile':<17}{'harness':<20}{'d success':>11}{'d turns':>14}{'d wasted':>14}"
              f"{'turns both ok':>16}{'wasted both ok':>17}{'d harness':>11}")
        for p in order_p:
            for h in order_h:
                d = deltas.get((c, pb, p, h))
                if not d:
                    continue
                cells = {m: mean_ci(d[m]) for m in d}
                f = lambda m: f"{cells[m][0]:>+8.2f}±{cells[m][1]:<4.2f}"
                ok = lambda m: f"{cells[m][0]:>+9.2f}±{cells[m][1]:<4.2f}" if m in cells else "n/a"
                print(f"  {p:<17}{h:<20}{cells['success'][0]:>+11.3f}{f('turns'):>14}{f('wasted_turns'):>14}"
                      f"{ok('turns_ok'):>16}{ok('wasted_turns_ok'):>17}{cells['harness_turns'][0]:>+11.2f}")
        print("  success-matched churn vs basic (seeds where both solved the task; mean ± 95% CI)")
        print(f"  {'profile':<17}{'harness':<20}{'d final diff':>14}{'d total churn':>16}{'d churn ratio':>16}{'d extra lines':>16}")
        for p in order_p:
            for h in order_h:
                d = deltas.get((c, pb, p, h))
                if not d or "churn_ratio_ok" not in d:
                    continue
                g = lambda m: f"{mean_ci(d[m])[0]:>+8.2f}±{mean_ci(d[m])[1]:<4.2f}"
                print(f"  {p:<17}{h:<20}{g('final_diff_ok'):>14}{g('total_churn_ok'):>16}{g('churn_ratio_ok'):>16}{g('extra_diff_lines_ok'):>16}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Coding-agent efficiency benchmark (simulated agents, real repos).")
    ap.add_argument("--seeds", type=int, default=20, help="seeds per (profile, task, harness)")
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES),
                    choices=[*PROFILES, *HELDOUT_PROFILES])
    ap.add_argument("--heldout", action="store_true", help="use the held-out profiles from HELDOUT.md")
    ap.add_argument("--harnesses", nargs="+", default=list(MAIN_HARNESSES), choices=list(HARNESSES))
    ap.add_argument("--ablation", action="store_true",
                    help="basic + full adaptive + gate-only, rules-only and leave-one-rule-out variants")
    ap.add_argument("--tasks", nargs="+", default=[t.name for t in TASKS], choices=list(TASKS_BY_NAME))
    ap.add_argument("--compliance", nargs="+", type=float, default=[0.5],
                    help="P(agent acts on a harness directive)")
    ap.add_argument("--plan-benefit", nargs="+", type=float, default=[0.0],
                    help="reduction of wrong-edit rate after a plan phase")
    ap.add_argument("--sweep", action="store_true", help="compliance 0..1 x plan_benefit {0, 0.5}")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--out", default="results")
    ap.add_argument("--save-trajectories", action="store_true", help="write every event to trajectories.jsonl")
    ap.add_argument("--no-cache", action="store_true", help="run the test subprocess on every single test turn")
    args = ap.parse_args(argv)

    if args.heldout:
        args.profiles = list(HELDOUT_PROFILES)
    if args.ablation:
        args.harnesses = list(ABLATION_HARNESSES)
    if args.sweep:
        args.compliance, args.plan_benefit = [0.0, 0.25, 0.5, 0.75, 1.0], [0.0, 0.5]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    traj_file = open(out / "trajectories.jsonl", "w") if args.save_trajectories else None
    tasks = [TASKS_BY_NAME[n] for n in args.tasks]
    total = (len(args.compliance) * len(args.plan_benefit) * len(args.profiles)
             * len(args.harnesses) * len(tasks) * args.seeds)
    rows, done, t0 = [], 0, time.perf_counter()

    for c in args.compliance:
        for pb in args.plan_benefit:
            for profile in args.profiles:
                for task in tasks:
                    for seed in range(args.seeds):
                        for harness in args.harnesses:
                            traj, metrics = run_one(task, harness, profile, seed, c, pb,
                                                    args.max_turns, use_cache=not args.no_cache)
                            rows.append({"compliance": c, "plan_benefit": pb, "profile": profile,
                                         "task": task.name, "seed": seed, "harness": harness, **metrics})
                            if traj_file:
                                traj_file.write(json.dumps(traj.to_dict()) + "\n")
                            done += 1
                            if done % 500 == 0:
                                print(f"  {done}/{total} runs ({time.perf_counter()-t0:.0f}s)", file=sys.stderr)
    if traj_file:
        traj_file.close()

    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = summarize(rows)
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)

    deltas = paired_deltas(rows)
    paired_rows = []
    for (c, pb, profile, harness), d in sorted(deltas.items()):
        row = {"compliance": c, "plan_benefit": pb, "profile": profile, "harness": harness}
        for m, vals in d.items():
            mean, ci = mean_ci(vals)
            row[f"d_{m}"], row[f"d_{m}_ci95"], row[f"n_{m}"] = mean, ci, len(vals)
        paired_rows.append(row)
    if paired_rows:
        fields = sorted({k for r in paired_rows for k in r}, key=lambda k: (k not in ("compliance", "plan_benefit", "profile", "harness"), k))
        with open(out / "paired.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(paired_rows)
    print_tables(summary, deltas)
    print(f"\n{done} runs in {time.perf_counter()-t0:.1f}s -> {out}/runs.csv, {out}/summary.csv, {out}/paired.csv")
    print("Note: agents are simulated; repositories, edits, diffs and test runs are real.")


if __name__ == "__main__":
    main()
