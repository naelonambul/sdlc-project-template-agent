# Implementation Plan

## Summary

Run the control-plane suite in parallel shards so the registered `control-plane` check finishes in under 15 seconds locally. This is change B from `test-speedup`'s plan (revision 2). `test-speedup` brought the sequential suite down to a floor of about 40s. Going further needs parallelism, not faster calls.

A new runner, `scripts/tests/run.py`, discovers the same tests `unittest discover` finds. It splits them by `TestCase` class into N shards, runs each shard as its own `python3 -m unittest` process, and fails unless every shard passes and the shards together ran exactly the discovered tests. `checks.json` registers the runner as the `control-plane` argv. `python3 -m unittest discover -s scripts/tests -t .` keeps working unchanged as the sequential path.

## Measurements (at `2756544`, macOS, 10 cores)

- Sequential suite: 278 tests, 40.8s.
- Per module: `test_status` 22.2s (130 tests), `test_approve_close` 8.5s, `test_verify` 4.7s, `test_guard` 2.3s, `test_new` 2.3s, `test_support` 1.2s, `test_workflow` 0.1s. Module shards alone would leave a 22s critical path.
- Per class: 40 classes. The heaviest are `test_status.Closure` 4.9s, `test_verify.Verify` 4.5s and `test_approve_close.Close` 3.2s. The slowest single test takes 1.2s. Class shards give a critical path of about 5s plus process start.
- No class shares state with another: the only `setUpClass` is `test_workflow`'s, which reads files. The fixture template is built per process. Every test works in its own temporary directory. The `ps` leak check looks only at children of its own process.

## Files and components that change

- `scripts/tests/run.py` (new, standard library only):
  - discovers with `unittest.defaultTestLoader.discover("scripts/tests", top_level_dir=".")` from the repository root; a discovery error (`unittest.loader._FailedTest`) fails the run;
  - groups test ids by `module.Class`, then assigns classes to shards greedily (largest test count first, to the least-loaded shard). The assignment is deterministic, so a failure reproduces with the same `--jobs`;
  - runs each shard as `sys.executable -m unittest <ids...>`, from the repository root with the parent's environment (so `SDLC_TEST_SUBPROCESS` and `SDLC_TEST_EQUIVALENCE` still apply), at most `--jobs` at a time;
  - `--jobs N`, default `min(os.cpu_count(), 8)`, overridable with `SDLC_TEST_JOBS`. `--jobs 1` runs the whole discovered suite in one `unittest` process, which is the sequential path;
  - prints each shard's result in shard order. A failed shard prints its full output. The last line summarizes: tests run, failures, errors, skips, and wall time;
  - exits 0 only if every shard exits 0 and the sum of the shards' `Ran N tests` equals the discovered count. Any other case exits 1 and names the reason, including a shard that crashed or printed no `Ran` line.
- `scripts/tests/test_run.py` (new): runner tests (see Tests and proof). They drive `run.py` against small synthetic test directories in a temporary directory, never against the real suite, so the suite does not recurse into itself.
- `checks.json`: the `control-plane` argv becomes `["python3", "scripts/tests/run.py"]`. id, group, cwd, timeout, paths and requires stay unchanged.
- `scripts/README.md`: name `python3 scripts/tests/run.py` as the default command, keeping the `unittest discover` line as the sequential equivalent.

Out of scope:
- `.github/workflows/repository.yml`. Its `control-plane-tests` job keeps running the sequential `unittest discover -v`. It duplicates `verify-core`, and removing or changing it is the separate `ci-dedupe` change, because a workflow change needs an owner push first.
- `repo.py` and `guard.py`.
- Reducing git calls per `status` (option C in `test-speedup`).

## Order of work

1. `scripts/tests/test_run.py` with the runner tests, all failing because `run.py` does not exist. Proof: `python3 -m unittest scripts.tests.test_run` fails.
2. `scripts/tests/run.py`. Proof: `python3 -m unittest scripts.tests.test_run` passes, and `python3 scripts/tests/run.py` passes with the same test count as `python3 -m unittest discover -s scripts/tests -t .`.
3. `checks.json` and `scripts/README.md`. Proof: `python3 scripts/repo.py verify --change parallel-tests --full` passes and its log shows the runner's summary line.
4. Sensitivity and timing (see Tests and proof), then `status` and `verify --full` at the final commit.

## Tests and proof

- **Runner tests** (`test_run.py`), each against a synthetic test directory:
  - all passing: exit 0, and the summary count equals the discovered count;
  - one failing test in one class: exit 1, and the failing shard's output, which names the test, is printed;
  - an erroring test, and a test module that fails to import: exit 1;
  - a shard process killed by a signal, or one that exits 0 without a `Ran` line (simulated by a test module that calls `os._exit(0)`): exit 1 with "count mismatch" or "crashed";
  - skips are counted and do not fail the run;
  - classes stay whole: the tests of a class never land in two shards;
  - the assignment is deterministic for a given `--jobs`, and `--jobs 1` runs one process;
  - `SDLC_TEST_JOBS` sets the default, and `--jobs` overrides it.
- **Same tests, same result:** the runner and `unittest discover` report the same test count and both pass, in default, `SDLC_TEST_SUBPROCESS=1` and `SDLC_TEST_EQUIVALENCE=1` modes.
- **Sensitivity:** in a scratch copy, two of `test-speedup`'s mutations (status ok inverted, approve leaking its Context) make the runner exit 1, failing the same tests as `unittest discover`.
- **Speed:** 3 alternating runs of the sequential command and the runner at default jobs, on the same commit. Pass: the runner's median is under 15s. Also reported, not gated: `--jobs 4` (the CI runner's vCPU count) and `--jobs 2`.
- **Leaks:** `python3 -W error::ResourceWarning scripts/tests/run.py` passes. The flag reaches the shards through `PYTHONWARNINGS`, which the runner sets from `sys.warnoptions`.
- `python3 scripts/repo.py status --change parallel-tests` and `python3 scripts/repo.py verify --change parallel-tests --full` pass.

## Risks and mitigations

- **Riskiest step: the count check in step 2.** A runner that drops tests reports green. Mitigations: the run passes only if the shards' combined `Ran` count equals the discovered count; discovery errors fail the run; the runner tests include a shard that silently exits early.
- **Hidden ordering dependencies between classes** would fail only under some shard assignments. Measured: none found (see Measurements). The assignment is deterministic, so a failure reproduces. `--jobs 1` and `unittest discover` stay available to compare.
- **Load on a small machine:** too many parallel git processes can slow the run down. The default is capped at 8, and `SDLC_TEST_JOBS` overrides it.
- **Output interleaving:** shards are buffered and printed whole in shard order, never interleaved.
- **`verify` timeout:** unchanged at 600s. The runner is faster, so the margin only grows.

## Rollback or recovery

Open a new change that sets the `control-plane` argv in `checks.json` back to `python3 -m unittest discover -s scripts/tests -t .`. `run.py` and its tests can stay or be removed in that change. Nothing else depends on the runner.

## Open questions

- Should the CI `control-plane-tests` job use the runner too, or be removed as a duplicate of `verify-core`? Left to `ci-dedupe`. Either way it needs an owner push.
- This packet was drafted on top of the unmerged `test-speedup` branch (`base.commit` `2756544`). After PR #47 merges, the packet is recreated from updated `main` with this plan, so `base.commit` is on the baseline before approval.
