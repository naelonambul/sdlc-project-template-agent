# Implementation Plan

## Summary

A read-only review of `main` at `217fd99` by Codex (`gpt-6-astra`) and Antigravity (`gemini-4-argon-high`) found ways for the control-plane test gate to report success without running the tests. I reproduced each of them before writing this plan:

1. **The runner exits 0 without running anything** when a test module's `load_tests` raises `SystemExit(0)`, or a test module calls `os._exit(0)` at import. Discovery runs inside the runner's own process, so the test code ends that process before the count check. Reproduced: a synthetic suite with a failing test plus such a module makes `run.py` exit 0 with no output. CI reads only the exit code, so both `control-plane-tests` and `verify-core` would pass.
2. **The workflow invariant reads only the first line of a `run:` value.** A YAML plain scalar continues on more-indented lines, so `run: python3 scripts/tests/run.py` followed by an indented `|| true` is the single command `python3 scripts/tests/run.py || true`. The invariant reports no findings for it. Reproduced, and checked with PyYAML, which reads that command.
3. **A class or module skipped in `setUpClass`/`setUpModule` fails the run.** Unittest reports one skip for the class and does not count its tests as run, so the count check reports a mismatch. This is a false failure, not a false pass, but it blocks a legitimate pattern. Reproduced: `count mismatch: ran 0, discovered 2`.

The fix makes the runner's parent process decide pass or fail from machine-readable results written by its child processes, instead of trusting the exit code of a process that test code can end, or parsing text that test code can print. It also makes the workflow invariant refuse any `run:` form it cannot read exactly.

Out of scope, judged not worth doing now: the `status` git-call reuse, shard balancing by measured cost, splitting `test_status.Closure`, `Context` as a context manager, and the `sys.path` and encoding cleanups in `support.py`. They are performance or tidiness items without a current defect.

## Files and components that change

- `scripts/tests/run.py`:
  - **Discovery in a child process.** The parent runs `sys.executable run.py --discover <file>`. The child discovers with the same loader and writes JSON: test ids per `module.Class`, the discovery errors, and `"complete": true`. The parent requires exit 0, a readable file and `complete`. Anything else fails the run with "discovery did not complete". The parent process never imports test code.
  - **Shards report through a result file.** The parent runs each shard as `sys.executable run.py --shard <file> <ids...>`. The worker loads exactly those ids with `unittest.TestLoader().loadTestsFromName` and runs them with `unittest.TextTestRunner` writing to stderr, so the human-readable output stays the same. A `TextTestResult` subclass records the id of every started test, failures, errors, skips with their test or fixture, and expected and unexpected outcomes. At the end the worker writes `{"started": [...], "fixture_skips": [...], "failures": n, "errors": n, "skipped": n, "unexpected_successes": n, "successful": bool, "complete": true}`.
  - **The parent's verdict per shard.** The shard fails unless:
    - the result file exists and has `complete`;
    - `successful` is true and the exit code is 0;
    - every assigned id was started, or belongs to a class or module whose `setUpClass`/`setUpModule` raised `SkipTest`, as recorded in `fixture_skips`;
    - no id outside the assignment was started.

    A shard process killed by a signal is still reported as crashed. The stderr summary parsing (`RAN`, `STATUS`, `parse`) is removed.
  - The run's last line keeps its form: `OK: ran N tests in K shards (...)` or `FAILED: ...; <reasons>`. N counts started tests plus tests covered by a fixture skip.
- `scripts/tests/test_run.py`:
  - new cases:
    - `load_tests` raising `SystemExit(0)`: exit 1, "discovery did not complete";
    - `os._exit(0)` at import of a test module: exit 1;
    - `sys.exit(0)` at import: exit 1, a discovery error, which already worked;
    - `setUpClass` raising `SkipTest`: exit 0, the class's tests counted as skipped;
    - `setUpModule` raising `SkipTest`: exit 0;
    - a test that calls `sys.exit(0)` inside the test: exit 1, as an error;
    - a test that prints a fake unittest summary to stderr: no effect on the verdict.
  - existing cases are kept. The cases that asserted the text-parsing messages ("ambiguous test summary", "no test summary") are changed to assert the new messages for the same situations ("no result", which now replaces both). The behaviour they protect, exit 1, is unchanged.
- `scripts/tests/test_workflow.py`, `control_plane_job_findings`:
  - every `run:` value must be a single-line plain scalar: not a `|` or `>` block scalar, not quoted, and the next non-blank line must start a new step (`      - `) or end the job block;
  - the job block must not contain `shell:`, `env:`, `defaults:` or `container:`, and the workflow must not contain a top-level `defaults:`;
  - new mutation cases asserted inside the test: an indented continuation line `|| true`, a `run: |` block scalar, a `shell:` key, a job-level `env:`, and a top-level `defaults:` with `run: shell:`.

No change to `checks.json`, `.github/workflows/repository.yml`, `repo.py`, `guard.py` or `support.py`. The workflow still runs `python3 -m unittest scripts.tests.test_run` and then `python3 scripts/tests/run.py`, so no owner push is needed.

## Order of work

1. `scripts/tests/test_run.py` and `scripts/tests/test_workflow.py`: the new cases. Proof: `python3 -m unittest scripts.tests.test_run scripts.tests.test_workflow` fails on exactly the new cases that encode the three defects.
2. `scripts/tests/test_workflow.py`: the stricter `control_plane_job_findings`. Proof: `python3 -m unittest scripts.tests.test_workflow` passes.
3. `scripts/tests/run.py`: discovery child, shard worker, parent verdict, with the parsing removed. Proof: `python3 -m unittest scripts.tests.test_run` passes, and `python3 scripts/tests/run.py` passes with the same test count as `python3 -m unittest discover -s scripts/tests -t .`.
4. Full proof (below), then `python3 scripts/repo.py status --change runner-integrity` and `python3 scripts/repo.py verify --change runner-integrity --full`.

## Tests and proof

- **Defects reproduced first:** step 1's new cases fail on the current code for defects 1, 2 and 3. They are the reproductions above, written as tests.
- **Same tests, same result:** the runner and `unittest discover` pass with the same count in default, `SDLC_TEST_SUBPROCESS=1` and `SDLC_TEST_EQUIVALENCE=1` modes. `python3 -W error::ResourceWarning scripts/tests/run.py` passes.
- **Sensitivity:** in a scratch copy, the two mutations used for `parallel-tests` (status ok inverted, approve leaking its Context) make the runner exit 1, failing the same tests as `unittest discover`.
- **Speed:** 3 runs at default jobs. Pass: median under 15s, the `parallel-tests` target. The extra discovery process is expected to add well under a second.
- `python3 scripts/repo.py status --change runner-integrity` and `python3 scripts/repo.py verify --change runner-integrity --full` pass.
- **CI:** the pull request's `repository` run on the final head is `success`.

## Risks and mitigations

- **Riskiest step: the parent's verdict (step 3).** It replaces the count check with a set check. Mitigations:
  - the verdict requires every assigned id started or fixture-skipped, and nothing else started;
  - each early-exit path has its own test;
  - the full suite must report the same count as `unittest discover`.
- **Fixture-skip attribution.** Unittest reports a `setUpClass` skip as a placeholder whose description names the class (`setUpClass (module.Class)`) and a `setUpModule` skip as one naming the module. The worker records these from the placeholder's description. A format change in a future Python would surface as a mismatch, which fails closed, not open.
- **Deliberately faked results.** A test could write a forged result file. This plan defends against accidental and ordinary early exits, not against test code written to subvert its own runner; review covers that.
- **Workflow invariant rejects valid YAML forms.** It is meant to: the job's two commands have one accepted spelling. A legitimate future need for another form is a change to this test, reviewed with the workflow change.

## Rollback or recovery

Open a new change that restores `run.py`, `test_run.py` and `test_workflow.py` from `217fd99`. No other file depends on the result-file format.

## Open questions

None.
