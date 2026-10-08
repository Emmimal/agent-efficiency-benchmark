# Held-out behaviours: pre-registration

Written BEFORE any held-out run. Do not edit the predictions after seeing results; if the design
changes, add a dated "Amendment" section at the bottom and say why.

## Why

The ablation showed that R5 (edit to a file the tests do not import) does nearly all of adaptive's
waste reduction, and R5 detects exactly the failure the simulator injects (edits to decoy files).
This suite removes that failure mode and tests whether adaptive still helps.

## Design

Four new profiles. In all of them `overwork = 0` and `decoy_share = 0`, so the agent NEVER edits
a file outside the tested module. R5 therefore cannot fire (a unit test checks this), and
`premature_stop = 0`, so the finish gate is irrelevant and success should be close to 100% for
every harness.

| profile | wrong_file | repeat_failure | revert | oscillate | rerun_pass | core_thrash |
|---|---|---|---|---|---|---|
| held_oscillate | 0.35 | 0.05 | 0 | 0.6 | 0 | 0 |
| held_rerun | 0.05 | 0.05 | 0 | 0 | 0.5 | 0 |
| held_core_thrash | 0.05 | 0.05 | 0 | 0 | 0 | 0.6 |
| held_mixed | 0.25 | 0.10 | 0.05 | 0.4 | 0.3 | 0.3 |

* **oscillate**: after reverting a wrong fix, re-applies the same wrong fix with this probability
  (edit, revert, same edit again).
* **rerun_pass**: re-runs already-passing tests unchanged, up to 3 times, before finishing.
* **core_thrash**: after the tests pass, makes a pointless cosmetic edit (adds a docstring) in the
  correct file, `app/core.py`. This is invisible to R5 and to the file-level "unrelated file"
  waste definition.

New metric, defined before running: `extra_diff_lines` = lines in the final diff beyond the
reference fix (successful runs only). It measures patch cleanliness directly.

Honest overlap: oscillation is the behaviour R2 was written for, and rerun-after-pass can trip R3
(three turns without a state change). So these are stress tests of R2/R3, not blind tests. The
core-thrash cosmetic edit can trip R2 (same file modified twice) and R4 (stray edit after a pass).
No rule was designed to be blind to all of them.

## Predictions (success-matched, paired vs basic)

Primary (H0): on every held-out profile, at both compliance 0.5 and 1.0, adaptive's difference in
wasted turns vs basic has a 95% interval that includes zero or is positive. I.e. adaptive does
NOT show a demonstrated waste reduction once R5's target is absent.

Secondary:
1. held_oscillate: adaptive does not break the cycle (R2's response only reviews the diff), so
   waste is not reduced and harness turns are positive.
2. held_rerun: R3's response does not stop reruns, so waste is not reduced, harness turns >= 0.
3. held_core_thrash: adaptive INCREASES measured waste (cleaning up the cosmetic edit turns it
   into an edit that is "reverted later") while REDUCING `extra_diff_lines` toward 0. If so, the
   waste metric and patch cleanliness disagree, which is itself a finding about the metric.
4. held_mixed: no waste reduction; higher total turns than basic on seeds both solve.
5. Structured: more total turns than basic everywhere, no waste reduction.
6. Success is ~100% for every harness (the gate has nothing to catch).

## Analysis plan

50 seeds, 10 tasks, harnesses basic / structured / adaptive, compliance 0.5 and 1.0,
plan_benefit 0. Report every cell, not only the ones that agree with the predictions.
Rule ablations on this suite are exploratory and labelled as such.

## Amendments

(none yet)

## Results (one run, exactly as pre-registered: 50 seeds, compliance 0.5 and 1.0)

`python -m agent_efficiency --seeds 50 --heldout --compliance 0.5 1.0 --out results_heldout`

Success-matched wasted turns, adaptive minus basic (mean ± 95% CI):

| profile | compliance 0.5 | compliance 1.0 | prediction |
|---|---|---|---|
| held_oscillate | -0.91 ± 0.27 | -1.67 ± 0.36 | **wrong**: predicted no reduction |
| held_rerun | +0.00 ± 0.04 | +0.03 ± 0.04 | held |
| held_core_thrash | +0.48 ± 0.05 | +0.66 ± 0.05 | held (waste rises, extra diff lines fall) |
| held_mixed | +0.05 ± 0.12 | -0.09 ± 0.17 | held |

* Primary prediction H0 held on 3 of 4 profiles and failed on held_oscillate.
* Secondary 1 (oscillation not broken, no waste reduction) FAILED. Secondary 2, 3, 4, 5 held.
  Secondary 6 held with a nuance: held_oscillate success is 97-100% because the 40-turn cap
  truncates long oscillations.
* held_core_thrash: the waste metric and patch cleanliness disagree. Adaptive raises measured
  waste (+0.48/+0.66) while lowering extra diff lines (-0.45/-0.60).

## Amendment (post-hoc, exploratory): why held_oscillate failed

In the pre-registered implementation a harness cleanup revert does not make the agent remember
the edit, so the agent does not re-apply it. That is a simulator assumption I did not foresee.
Sensitivity run where the agent still wants to re-apply an edit the harness reverted:

| | wasted (adaptive - basic) | total turns (adaptive - basic) |
|---|---|---|
| as pre-registered, 0.5 / 1.0 | -0.91±0.27 / -1.67±0.36 | -0.32±0.31 / -0.42±0.37 |
| agent persists, 0.5 / 1.0 | -0.62±0.25 / -1.21±0.32 | +0.15±0.33 / +0.59±0.43 |

The waste reduction shrinks by about a third but does not vanish; the net turn advantage does.
The remaining reduction was not isolated further.
