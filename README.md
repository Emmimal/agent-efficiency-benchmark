# agent-efficiency-benchmark

A pure-Python benchmark that measures the hidden work behind passing coding-agent runs: wasted turns, reverted edits and patch churn. Simulated agents, real repositories.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)


Most coding-agent benchmarks score the end state: did the final patch pass the tests. This one records what happened before that, and keeps two quantities apart:

- **Final patch size**: lines changed between the starting repository and the final one.
- **Total work**: everything the agent did on the way, including edits it later undid.

Companion write-up on Towards Data Science: *AI Coding Agents Can Solve the Task — But How Much Work Did They Waste?*

> **Read this first.** The agent's decisions are simulated by seeded Python policies. The repositories, edits, diffs and `unittest` runs are real. No language model, API or download is involved, and nothing here measures how Claude Code, Codex or any real coding agent behaves. The results describe how harness rules behave against controlled failure behaviors.

## What It Does

```text
        SIMULATED                              REAL
  +--------------------+          +---------------------------------+
  | agent decisions    |  ----->  | harness: basic / structured /   |
  | (seeded profiles)  |          |          adaptive               |
  +--------------------+          +----------------+----------------+
                                                   |
                          edits, diffs, subprocess unittest runs
                                                   v
                                  +---------------------------------+
                                  | temp repository on disk         |
                                  +----------------+----------------+
                                                   |
                                  one immutable event per turn
                                                   v
                                  +---------------------------------+
                                  | trajectory recorder             |
                                  +----------------+----------------+
                                                   v
                                  +---------------------------------+
                                  | efficiency analyzer             |
                                  | wasted turns, churn, harness    |
                                  | turns, final diff               |
                                  +---------------------------------+
```

Seven components, one command:

| Component | Job |
|---|---|
| **Simulated agent** | a sensible policy (run tests, read the failure, edit, re-run, finish) plus profile-driven deviations (`agent.py`) |
| **Harness** | basic, structured or adaptive wrapper between the agent and the repository (`harness.py`) |
| **Repository** | real temp directory: edits, state hashing, diffs, subprocess `unittest` runs (`repo.py`) |
| **Recorder** | one immutable event per turn, raw facts only (`recorder.py`) |
| **Analyzer** | derives waste, churn and patch metrics from the events (`analyzer.py`) |
| **Experiment runner** | grid runs, paired deltas, ablations, CSV output (`experiment.py`) |
| **Trajectory viewer** | prints one run through each harness, with the real final diff (`show.py`) |

## Installation

```bash
git clone https://github.com/Emmimal/agent-efficiency-benchmark.git
cd agent-efficiency-benchmark
python -m unittest discover -s tests -t .
```

Python 3.10 or newer. Standard library only, so there is nothing to `pip install`. Developed and tested on Python 3.12; the author also ran every experiment on Windows. `pip install -e .` is optional and adds an `agent-efficiency` command.

## Quick Start

```bash
python -m agent_efficiency --seeds 20
```

2,400 runs (4 profiles x 3 harnesses x 10 tasks x 20 seeds). It prints summary tables, then paired comparisons against the basic harness, then success-matched churn. First block of the output:

```text
=== compliance=0.5  plan_benefit=0.0 ===
profile          harness                 n  succ%         turns        wasted  harness  failed  reverts  churn x
careful          basic                 200  92.5%    5.20±0.19    0.29±0.11     0.00    1.13     0.03     1.05
careful          structured            200 100.0%    7.66±0.20    0.44±0.14     2.12    1.13     0.07     1.14
careful          adaptive              200 100.0%    5.76±0.26    0.28±0.10     0.42    1.09     0.10     1.20
normal           basic                 200  77.5%    5.25±0.27    0.63±0.16     0.00    1.31     0.05     1.07
normal           structured            200 100.0%    8.82±0.33    1.31±0.25     2.35    1.33     0.14     1.22
normal           adaptive              200 100.0%    6.62±0.34    0.74±0.17     0.86    1.26     0.18     1.30
sloppy           basic                 200  51.5%    5.62±0.41    1.44±0.27     0.00    1.82     0.12     1.18
sloppy           structured            200 100.0%   11.91±0.62    3.15±0.37     3.10    2.08     0.53     1.81
sloppy           adaptive              200 100.0%    9.95±0.68    1.97±0.29     2.83    1.71     0.68     2.19
loop_prone       basic                 200  89.0%    7.45±0.46    2.46±0.37     0.00    2.30     0.08     1.12
loop_prone       structured            200 100.0%   11.59±0.56    3.85±0.43     2.48    2.33     0.45     1.67
loop_prone       adaptive              200 100.0%    9.04±0.56    2.29±0.31     1.97    1.75     0.51     1.83
```

Then look at one run turn by turn, with the real diff:

```bash
python -m agent_efficiency.show --profile loop_prone --pick adaptive-loses
```

```text
--- BASIC | task=off_by_one_range profile=loop_prone seed=6 compliance=0.5 plan_benefit=0.0
 # phase           action       target        result     +/-    flags                                   reason
 1 agent           run_tests                  FAIL#9778                                                 establish baseline
 2 agent           inspect      core.py       read                                                      read the failure
 3 agent           edit         core.py       applied    +1/-1                                          applies the fix
 4 agent           run_tests                  PASS                                                      test the change
 5 agent           edit         utils.py      applied    +1/-1  WASTED,unrelated-file                   unneeded tidy-up
 6 agent           run_tests                  PASS              WASTED                                  test the change
 7 agent           edit         config.py     applied    +1/-1  WASTED,unrelated-file                   unneeded tidy-up
 8 agent           run_tests                  PASS              WASTED                                  test the change
 9 agent           edit         utils.py      applied    +1/-1  WASTED,unrelated-file                   unneeded tidy-up
10 agent           run_tests                  PASS              WASTED                                  test the change
11 agent           finish                     done                                                      tests pass
   outcome: SOLVED | turns=11 wasted=6 harness_turns=0 failed_runs=1 reverted=0 final_diff=8 total_churn=8
```

The viewer takes the first match in a fixed scan, so the pick is reproducible. A picked run illustrates what the metrics mean. It is not a typical run.

The `FAIL#xxxx` suffix is a short hash of the test output. Tracebacks differ between platforms and Python versions, so you will see a different suffix on your machine. The metrics only compare whether two outputs are equal, so they do not depend on the value.

## Running the Experiments

| Experiment | Command | Runs | Output |
|---|---|---|---|
| Main comparison | `python -m agent_efficiency --seeds 20 --out results/main` | 2,400 | `results/main/` |
| Compliance sweep | `python -m agent_efficiency --seeds 20 --sweep --out results/sweep` | 24,000 | `results/sweep/` |
| Rule ablations | `python -m agent_efficiency --seeds 20 --ablation --compliance 0.5 1.0 --out results/ablation` | 14,400 | `results/ablation/` |
| Held-out suite | `python -m agent_efficiency --seeds 50 --heldout --compliance 0.5 1.0 --out results/heldout` | 12,000 | `results/heldout/` |

On the author's Windows laptop these take roughly 1, 4, 3 and 2.5 minutes. The main comparison is the compliance 0.5, plan benefit 0 block of the sweep, so it is not committed separately. The committed `results/` folders are the output of the three larger commands.

## What the Benchmark Found

Everything below comes from simulated agents. Read it as a statement about harness rules, not about real agents.

**Main comparison** (compliance 0.5, 200 runs per cell, mean ± 95% interval):

| Profile | Harness | Success | Turns | Wasted turns | Harness turns |
|---|---|---|---|---|---|
| careful | basic | 92.5% | 5.20 ± 0.19 | 0.29 ± 0.11 | 0.00 |
| careful | structured | 100.0% | 7.66 ± 0.20 | 0.44 ± 0.14 | 2.12 |
| careful | adaptive | 100.0% | 5.76 ± 0.26 | 0.28 ± 0.10 | 0.42 |
| normal | basic | 77.5% | 5.25 ± 0.27 | 0.63 ± 0.16 | 0.00 |
| normal | structured | 100.0% | 8.82 ± 0.33 | 1.31 ± 0.25 | 2.35 |
| normal | adaptive | 100.0% | 6.62 ± 0.34 | 0.74 ± 0.17 | 0.86 |
| sloppy | basic | 51.5% | 5.62 ± 0.41 | 1.44 ± 0.27 | 0.00 |
| sloppy | structured | 100.0% | 11.91 ± 0.62 | 3.15 ± 0.37 | 3.10 |
| sloppy | adaptive | 100.0% | 9.95 ± 0.68 | 1.97 ± 0.29 | 2.83 |
| loop_prone | basic | 89.0% | 7.45 ± 0.46 | 2.46 ± 0.37 | 0.00 |
| loop_prone | structured | 100.0% | 11.59 ± 0.56 | 3.85 ± 0.43 | 2.48 |
| loop_prone | adaptive | 100.0% | 9.04 ± 0.56 | 2.29 ± 0.31 | 1.97 |

Raw turn counts flatter the harness that fails most, because an agent that quits early is short and cheap. To compare cost fairly, restrict to seeds where both harnesses solved the task and compare run by run:

| Profile | Harness | Matched pairs | Extra turns vs basic | Extra wasted turns vs basic |
|---|---|---|---|---|
| careful | structured | 185 | +2.16 ± 0.08 | +0.12 ± 0.07 |
| careful | adaptive | 185 | +0.23 ± 0.12 | -0.04 ± 0.05 |
| normal | structured | 155 | +2.52 ± 0.16 | +0.46 ± 0.15 |
| normal | adaptive | 155 | +0.37 ± 0.17 | -0.01 ± 0.10 |
| sloppy | structured | 103 | +3.13 ± 0.29 | +0.86 ± 0.27 |
| sloppy | adaptive | 103 | +1.05 ± 0.51 | -0.41 ± 0.29 |
| loop_prone | structured | 178 | +3.46 ± 0.27 | +1.14 ± 0.25 |
| loop_prone | adaptive | 178 | +1.10 ± 0.51 | -0.30 ± 0.32 |

Five findings:

1. **Basic looks cheapest and fails most.** A sloppy agent under the basic harness solves 51.5% of tasks, because it declares itself done while tests still fail.
2. **The completion gate accounts for the entire success gain.** A variant with only the gate (no rules) matches the full adaptive harness on success. On matched seeds it equals basic exactly: 0.00 ± 0.00 extra wasted turns in all four profiles. Early quitting is built into the simulator, so a gate that stops it works by construction. The size of the effect is the useful part.
3. **One rule does nearly all the waste reduction.** At compliance 1.0, adaptive's change in wasted turns is -0.70 ± 0.35 with R5, -0.30 ± 0.36 without for sloppy agents and -0.83 ± 0.32 with R5, -0.26 ± 0.33 without for loop-prone agents. R5 fires when an agent edits a file the tests do not import, and the simulator injects exactly that behavior. That is the circularity the held-out suite tests.
4. **Structured never reduces waste.** It adds 2.16 to 3.46 turns on matched seeds across all four profiles.
5. **Waste and patch cleanliness can disagree.** A harness that cleans up pointless edits gives a smaller final patch but more total churn, and the waste metric can score it worse.

**Held-out suite** (profiles that never edit an unrelated file, so R5 cannot fire):

| Held-out profile | Compliance | Adaptive: extra wasted turns | Structured: extra wasted turns | Adaptive: extra diff lines |
|---|---|---|---|---|
| held_oscillate | 0.5 | -0.91 ± 0.27 | +0.00 ± 0.00 | +0.00 ± 0.00 |
| held_oscillate | 1.0 | -1.67 ± 0.36 | +0.00 ± 0.00 | +0.00 ± 0.00 |
| held_rerun | 0.5 | +0.00 ± 0.04 | +0.71 ± 0.08 | +0.00 ± 0.00 |
| held_rerun | 1.0 | +0.03 ± 0.04 | +0.71 ± 0.08 | +0.00 ± 0.00 |
| held_core_thrash | 0.5 | +0.48 ± 0.05 | +0.29 ± 0.04 | -0.45 ± 0.04 |
| held_core_thrash | 1.0 | +0.66 ± 0.05 | +0.60 ± 0.04 | -0.60 ± 0.04 |
| held_mixed | 0.5 | +0.05 ± 0.12 | +0.66 ± 0.07 | -0.21 ± 0.04 |
| held_mixed | 1.0 | -0.09 ± 0.17 | +0.82 ± 0.08 | -0.29 ± 0.04 |

The pre-registered prediction was no demonstrated waste reduction on any profile. It held for three and failed for `held_oscillate` (-0.91 ± 0.27 at compliance 0.5, -1.67 ± 0.36 at 1.0). The cause was a simulator assumption, documented with a sensitivity check in [`HELDOUT.md`](HELDOUT.md).

## The Three Harnesses

```text
   BASIC                STRUCTURED               ADAPTIVE

   task                 task                     task
    |                    |                        |
   agent --> tools      PLAN                     agent --> tools --+
    |                    |                        ^               |
   done                 IMPLEMENT                 |   watch the trajectory
                         |                        +-- R1..R5 step in when
                        TEST                          there is evidence
                         |                            of waste
                        REVIEW                      |
                         |                        gate: no "done"
                        done                      while tests fail
```

The adaptive rules were fixed before the first run:

| Rule | Fires when | Directive |
|---|---|---|
| R1 | the same command failed twice with no state change | diagnose before editing again |
| R2 | the same file was modified twice, or two reverts happened | inspect the accumulated diff |
| R3 | three turns passed with no state change | change strategy |
| R4 | tests pass after a messy run | verify by reviewing the diff |
| R5 | an edit touched a file the tests do not import | justify it or undo it |
| Gate | the agent tries to finish while tests fail | refuse |

Ablation harnesses (`--ablation`) are `adaptive-gate-only`, `adaptive-rules-only` and `adaptive-no-R1` to `adaptive-no-R5`. They were designed after seeing the first results, so treat them as exploratory.

## Agent Profiles

Each profile adds deviations to the baseline policy with fixed probabilities. **These numbers are hypothetical behavior classes, not measurements of real agents.**

| Profile | Wrong edit | Repeats a failing command | Reverts | Quits early | Unneeded edit after a pass |
|---|---|---|---|---|---|
| careful | 0.05 | 0.05 | 0.02 | 0.03 | 0.05 |
| normal | 0.15 | 0.15 | 0.08 | 0.08 | 0.15 |
| sloppy | 0.30 | 0.30 | 0.20 | 0.18 | 0.30 |
| loop_prone | 0.10 | 0.55 | 0.15 | 0.05 | 0.40 |

Held-out profiles (`--heldout`) never edit an unrelated file and never quit early:

| Profile | Behavior |
|---|---|
| held_oscillate | re-applies a wrong fix it just reverted (probability 0.6) |
| held_rerun | re-runs passing tests unchanged, up to three times (0.5) |
| held_core_thrash | makes a pointless cosmetic edit in the correct file after a pass (0.6) |
| held_mixed | a blend of the three |

How the agent reacts to a harness is explicit and sweepable: `--compliance` is the probability it acts on a directive instead of ignoring it, and `--plan-benefit` is how much a forced plan phase lowers its wrong-edit rate. The agent's random stream depends only on profile, task and seed, so every harness faces the same agent at the start of a run and comparisons are paired.

## Tasks

Ten tiny bugs, each in a temporary repository with an `app` package, a `unittest` suite, a reference fix, a plausible wrong fix in the right file, and shared decoy edits to unrelated files:

`off_by_one_range`, `boundary_comparison`, `empty_list_crash`, `wrong_formula`, `missing_strip`, `order_lost`, `slice_off_by_one`, `wrong_variable`, `branch_order`, `split_whitespace`

Success is decided by a hidden check: when a run ends, the tests run on the final repository state. The agent never sees that verdict.

## Waste Definition and Metrics

An action is **wasted** when it contributes no useful progress toward the final state. Counting every failed test as waste would be wrong, since a failing test after an edit is information. An action is wasted when it:

- repeats a state already observed: the same command on an unchanged repository, a test run whose output was already seen with no relevant file changed since, or a re-read of unchanged contents
- changes an irrelevant part of the repository, meaning a file the tests do not import
- is an edit that changes nothing, or one that is undone later

A recovery action such as a revert is not itself waste. The change it removes is. Turns caused by the harness (plan, review, gate, directives, cleanup) are counted separately as **harness turns**.

| Metric | Meaning |
|---|---|
| `success` | tests pass on the final state (hidden check) |
| `turns` | total turns, agent and harness |
| `wasted_turns`, `wasted_share` | agent turns that were waste, and as a share of all turns |
| `harness_turns` | turns caused by the harness |
| `failed_runs` | test runs that failed |
| `repeated_commands` | read or test commands re-run on an identical repository state |
| `reverted_edits`, `recovery_turns` | edits later undone, and the revert turns themselves |
| `unrelated_edits`, `files_touched` | edits to files the tests do not import, and distinct files changed |
| `final_diff` | lines added plus removed between the initial and final repository |
| `total_churn` | lines added plus removed across every edit and revert |
| `churn_ratio` | `total_churn / final_diff`, successful runs only |
| `extra_diff_lines` | final diff lines beyond the reference fix, successful runs only |

There is deliberately no single efficiency score.

## Configuration Reference

`python -m agent_efficiency [options]`

| Flag | Default | Meaning |
|---|---|---|
| `--seeds N` | 20 | seeds per (profile, task, harness) |
| `--profiles ...` | careful normal sloppy loop_prone | which profiles to run |
| `--heldout` | off | use the held-out profiles instead |
| `--harnesses ...` | basic structured adaptive | which harnesses to run |
| `--ablation` | off | basic, full adaptive, gate-only, rules-only and leave-one-rule-out variants |
| `--tasks ...` | all ten | restrict to named tasks |
| `--compliance F ...` | 0.5 | probability the agent acts on a harness directive |
| `--plan-benefit F ...` | 0.0 | reduction of the wrong-edit rate after a plan phase |
| `--sweep` | off | compliance 0, 0.25, 0.5, 0.75, 1.0 and plan benefit 0, 0.5 |
| `--max-turns N` | 40 | turn cap per run |
| `--out DIR` | results | output directory |
| `--save-trajectories` | off | write every event to `trajectories.jsonl` |
| `--no-cache` | off | run the test subprocess on every test turn |

`python -m agent_efficiency.show` takes `--task`, `--profile`, `--seed`, `--compliance`, `--plan-benefit`, `--harnesses` and `--pick adaptive-wins|adaptive-loses`.

## Output Files

Each run writes three files to `--out`:

- **`runs.csv`**: one row per run. Columns: `compliance, plan_benefit, profile, task, seed, harness, success, turns, wasted_turns, wasted_share, harness_turns, failed_runs, repeated_commands, reverted_edits, unrelated_edits, recovery_turns, files_touched, final_diff, total_churn, churn_ratio, extra_diff_lines`
- **`summary.csv`**: mean and 95% interval (`_ci95`) of each metric per (compliance, plan benefit, profile, harness).
- **`paired.csv`**: paired differences against the basic harness. `d_<metric>` is the mean difference, `d_<metric>_ci95` its interval and `n_<metric>` the number of pairs. The `_ok` variants use only seeds where both runs solved the task. Use these for any cost comparison.

## Project Structure

```text
agent-efficiency-benchmark/
├── agent_efficiency/
│   ├── __main__.py        # python -m agent_efficiency
│   ├── agent.py           # simulated agent, profiles, held-out profiles
│   ├── harness.py         # Session, basic / structured / adaptive harnesses, ablations
│   ├── repo.py            # real on-disk repository, diffs, state hashes, test runs
│   ├── recorder.py        # immutable Event, RunMeta, Trajectory
│   ├── analyzer.py        # waste, churn and patch metrics
│   ├── experiment.py      # grid runner, paired deltas, CSV output, CLI
│   ├── show.py            # turn-by-turn trajectory viewer
│   └── tasks.py           # ten seeded-bug tasks, reference and wrong fixes, decoys
├── tests/
│   └── test_pipeline.py
│   └── __init__.py
├── results/
│   ├── paired.csv             
│   ├── runs.csv          
│   └── summary.csv
├── results_ablation/
│   ├── paired.csv             
│   ├── runs.csv          
│   └── summary.csv
├── results_heldout/
│   ├── paired.csv             
│   ├── runs.csv          
│   └── summary.csv            
├── LICENSE
├── HELDOUT.md
└── README.md
```

## Reproducibility

- Every random choice is seeded from the profile, the task and the seed. The same command gives the same numbers.
- The committed held-out CSVs (`runs.csv`, `summary.csv`, `paired.csv`) were regenerated on a second machine running Linux and were byte-identical to the ones produced on the author's Windows machine. The other result tables matched the author's printed output.
- Test results are a pure function of (task, repository contents), so each distinct state is executed once per process and reused. A unit test checks that a cached result equals a fresh subprocess run, and `--no-cache` forces real execution every time.
- The test suite has 17 tests: task validity, decoy and cosmetic edits, a hand-scripted trajectory with known analyzer output, ablation plumbing, determinism, and a check that the held-out profiles never touch unrelated files.

## When to Use This

Worth it when you want to:

- compare harness rules, completion gates or intervention policies under controlled, repeatable failure behaviors
- build and test a trajectory analyzer before pointing it at real agent logs
- show the difference between final patch size and total work

Skip it when you:

- need to know how a real coding agent behaves, because none was run
- need realistic repositories, because the tasks are ten single-function bugs
- want a single efficiency number, because the benchmark deliberately has none

## Known Limitations

- The agent is simulated. The profile numbers and the compliance values are assumptions, not measurements.
- Ten tiny single-function tasks. Real repositories have multi-file bugs, flaky tests and slow builds.
- "Relevant file" means a file the tests import. A pointless edit inside the correct file escapes both rule R5 and the waste definition, as `held_core_thrash` shows.
- The simulated agent forgets an edit after a harness reverts it, which flatters the harness on `held_oscillate`. See the sensitivity check in `HELDOUT.md`.
- The rule ablations are post hoc, and the held-out suite overlaps with R2 and R3, so it is a stress test of those rules, not a blind test.
- The turn cap is 40. On `held_oscillate` at compliance 0.5, every unsuccessful run hit it.
- Structured's waste numbers may be inflated, because sending the agent back from "finish" gives its random deviations another roll. This was not tested.
- Intervals are normal approximations on paired means across many cells. A few cells will look significant by chance, so rely on trends across compliance levels and profiles, not on single cells.

## Related

Same author, other benchmarks and layers for LLM systems:

- [context-engine](https://github.com/Emmimal/context-engine): *RAG Isn't Enough — I Built the Missing Layer That Makes LLM Systems Work*. Retrieval, re-ranking, memory decay and token-budget enforcement in one pipeline.
- [context-graph-benchmark](https://github.com/Emmimal/context-graph-benchmark): *Vector RAG Isn't Enough — I Built a Context Graph Layer for Multi-Agent Memory*. Raw history, TF-IDF RAG and a context graph compared on multi-agent memory.
- [async-router-engine](https://github.com/Emmimal/async-router-engine): *LLM Rate Limits Corrupt Pipelines — I Built a Router to Fix It*. Typed error classification and execution state preservation for async LLM calls.
- [control-layer](https://github.com/Emmimal/control-layer): *Prompt Engineering Failed in Production — I Built the Control Layer That Actually Works*. An eight-component prompt control layer.

## Disclosure

No affiliation with, sponsorship from or financial interest in any organization or tool mentioned here. The author ran every experiment and checked the reported numbers against the output files.

## Citation

```bibtex
@software{alexander2026agentefficiency,
  author  = {Alexander, Emmimal P},
  title   = {Agent Efficiency Benchmark},
  year    = {2026},
  version = {1.0.0},
  url     = {https://github.com/Emmimal/agent-efficiency-benchmark}
}
```

## License

MIT
