# Implementation Plan

## Summary

`runner-integrity` met its speed target (median 14.3s against under 15s), but the margin shrank from the 11.5s of the `main` before it. The cause is shard assignment, not the new verdict mechanism:

- `scripts/tests/run.py` packs whole classes into at most `--jobs` fixed shards, balancing by test count.
- When `test_run.Runner` grew to 31 tests, that greedy assignment put `test_verify.Verify`, `test_approve_close.Approve`, `CarriedRevisionAfterClosure` and `PullRequestGate` in one shard. That shard takes 14.2s, while the lightest takes 7.1s.
- Test count is a poor proxy for cost, and any new test can reshuffle heavy classes together again.

This change runs **each test class in its own child process**, drawn from a pool of at most `--jobs` concurrent processes, classes with the most tests first. No packing is left to go wrong, and each class runs isolated from the others. The verdict from `runner-integrity` is unchanged; it simply applies to one class per shard.

## Measurements (at `932e69c`, macOS, 10 cores, same load, prototype in a scratch copy)

| Scheduling | `--jobs` | Wall time |
|---|---|---|
| fixed shards by test count (current) | 8 | 14.0–14.4s (3 runs) |
| one process per class, pool, heaviest first | 8 | 12.0–12.3s (3 runs) |
| one process per class | 6 / 10 | 13.1s / 11.8s |
| current / one process per class | 4 | 16.9s / 15.1s |

- The remaining critical path is `test_status.Closure`. Its 21 tests take 4.9s alone and 8–11s under the parallel load: about 75s of CPU, mostly git process system time, spread over a 12s wall. Splitting that class would gain more, but it changes a product test file and is not needed for the target.
- 41 classes means 41 processes instead of 8. The extra start-up cost is visible but smaller than the balancing gain even at `--jobs 4`.

## Decision

- **Chosen: one process per class from a bounded pool.**
  - It needs no cost estimate.
  - It is robust to new tests.
  - Class assignment, submission order and output order are deterministic. A class always runs in a process of its own, so no failure can come from sharing a process with another class. Failures that depend on load are not made reproducible by this; that was not true before either.
- **Rejected: balance fixed shards by measured cost.** A stored cost table drifts as tests change, and a timing cache adds state and nondeterminism.
- **Rejected: split heavy classes into per-test processes.** Classes with `setUpClass`/`setUpModule` must stay whole, and per-test processes multiply start-up cost.
- **Rejected for now: split `test_status.Closure`.** It is outside this change's files, and the target is met without it.

## Files and components that change

- `scripts/tests/run.py`:
  - **Shards.** With `--jobs` greater than 1, every class is its own shard. The shard list is ordered by descending test count, then class name, and submitted in that order to a `ThreadPoolExecutor(max_workers=jobs)`. Test count is the only cost proxy; this is not a measured cost. With `--jobs 1`, all classes form one shard run by one process, unchanged as the sequential path.
  - **Output.** One line per shard, printed after all shards finish, in the same order as submission, so the output shows the scheduling order. A failed shard's output is printed under its line. The summary line keeps its form: `OK: ran N tests in K shards (...)` / `FAILED: ...`.
  - **Unchanged:**
    - the discovery child;
    - the shard worker and its result file;
    - the verdict and its order;
    - duplicate-id refusal;
    - `SDLC_TEST_JOBS` and the default of `min(cpu count, 8)`;
    - the `PYTHONWARNINGS` hand-off.
  - `plan_shards` is replaced by the ordering above.
- `scripts/tests/test_run.py`:
  - `test_classes_stay_whole_and_assignment_is_deterministic` becomes `test_each_class_runs_alone_heaviest_first`. It uses classes with 3, 1, 2, 2 and 1 tests and `--jobs 2`. There must be 5 shard lines, each naming exactly one class with its own test count, ordered by descending test count, then name. Two runs must give the same lines, ignoring timings.
  - `test_jobs_from_environment_and_flag` and `test_never_more_shards_than_classes` become `test_jobs_sets_the_exact_concurrency`. This version uses no sleeps.
    - Each of 6 classes, on starting, creates a marker file in a shared directory.
    - It then waits, with a 10s timeout, until at least J markers exist, where J is given to it through the environment.
    - It records how many classes were running at that moment (started and not yet finished), then marks itself finished.
    - The highest recorded value must equal J exactly: 2 with `SDLC_TEST_JOBS=2`, and 4 with `--jobs 4` and `SDLC_TEST_JOBS=2`. The pool cannot exceed J, and the wait guarantees J overlap, so the assertion is exact and not timing-dependent. A pool smaller than J would stall at the wait, time out, and fail.
  - `test_set_up_module_skip_covers_only_that_module` keeps its `--jobs 1` runs and adds a `--jobs 2` run. The skipped module's two classes are then in two shards, each covered by the module's skip, and the prefix-named sibling module still runs: `OK: ran 4 tests ... skipped=2`.
  - `test_all_passing`: `in 3 shards` becomes `in 5 shards`, because 5 classes run as 5 shards with `--jobs 3`. This is the only existing assertion on a shard count with `--jobs` greater than 1.
  - `test_jobs_one_runs_one_process` and every other runner test are unchanged.
- `scripts/README.md`: "one process per group of `TestCase` classes" becomes "one process per `TestCase` class, at most `--jobs N` (or `SDLC_TEST_JOBS`) at a time".

No change to `checks.json`, the workflow, `repo.py`, `guard.py`, `support.py` or `test_workflow.py`.

## Order of work

1. `scripts/tests/test_run.py`: the replaced and adjusted tests. Proof: `python3 -m unittest scripts.tests.test_run` fails under the current packing on `test_each_class_runs_alone_heaviest_first` and on `test_all_passing`'s shard count. `test_jobs_bounds_concurrency` passes on both the current and the new code, because packing into `--jobs` shards also bounds concurrency. It guards the new pool's limit; it is not a reproduction.
2. `scripts/tests/run.py` and `scripts/README.md`. Proof: `python3 -m unittest scripts.tests.test_run` passes, and `python3 scripts/tests/run.py` passes with the same count as `unittest discover`.
3. Full proof, then `python3 scripts/repo.py status --change class-scheduling` and `python3 scripts/repo.py verify --change class-scheduling --full`.

## Tests and proof

- Runner and `unittest discover` pass with the same count in default, `SDLC_TEST_SUBPROCESS=1` and `SDLC_TEST_EQUIVALENCE=1` modes. `-W error::ResourceWarning` passes.
- **Sensitivity:** the two scratch-copy mutations (status ok inverted, approve leaking its Context) fail the same tests under both.
- **Speed:** 3 alternating runs of `main` (`932e69c`) and this change at default jobs, under the same load. Pass: this change's median is below 13s, and below `main`'s median. Reported, not gated: `--jobs 4`.
- `status` and `verify --full` pass. The pull request's `repository` run is `success`.

## Risks and mitigations

- **More processes.** 41 instead of 8 on this machine. Each builds its own fixture template once (`support._template`). This is measured above and gated by the speed criterion.
- **The concurrency test synchronizes instead of sleeping.** The wait has a 10s timeout, so a slow machine delays the test but cannot fail a correct pool.
- **A class that depends on running in the same process as another class** would break. Measured in `parallel-tests`: none does. Equivalence and subprocess modes run in full.

## Revision 2

The draft was reviewed read-only by Codex (`gpt-6-astra`) and Antigravity (`gemini-4-argon-high`). Both returned "approve with changes". This revision adopts their findings:

- The concurrency test now asserts the exact effective jobs value, so `--jobs` overriding `SDLC_TEST_JOBS` stays verified. It synchronizes with a timeout instead of relying on overlapping sleeps.
- Output follows submission order. The scheduling test uses classes of different sizes, so heaviest-first is tested.
- The `setUpModule` test gains a parallel run.
- The one shard-count assertion that changes is named.
- The determinism claim is narrowed, and "heaviest" is defined as most tests.

## Rollback or recovery

Open a new change that restores `scripts/tests/run.py`, `test_run.py` and `scripts/README.md` from `932e69c`.

## Open questions

None.
