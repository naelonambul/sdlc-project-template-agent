# Implementation Plan

## Summary

A read-only review of `main` at `217fd99` by Codex (`gpt-6-astra`) and Antigravity (`gemini-4-argon-high`) found ways for the control-plane test gate to report success without running the tests. I reproduced each one before writing this plan:

1. **The runner exits 0 without running anything.** This happens when a test module's `load_tests` raises `SystemExit(0)`, or when a test module calls `os._exit(0)` at import. Discovery runs inside the runner's own process, so the test code ends that process before the count check. Reproduced: a synthetic suite with a failing test plus such a module makes `run.py` exit 0 with no output. CI reads only the exit code, so both `control-plane-tests` and `verify-core` would pass.
2. **The workflow invariant reads only the first line of a `run:` value.** A YAML plain scalar continues on more-indented lines, so `run: python3 scripts/tests/run.py` followed by an indented `|| true` is the single command `python3 scripts/tests/run.py || true`. Reproduced: the invariant reports nothing, and PyYAML reads that command.
3. **A class or module skipped in `setUpClass`/`setUpModule` fails the run.** Unittest reports one skip for the class and does not count its tests as run, so the count check reports a mismatch. This is a false failure, not a false pass, but it blocks a legitimate pattern. Reproduced: `count mismatch: ran 0, discovered 2`.

The fix makes the runner's parent process decide pass or fail from machine-readable results that its child processes write. It no longer trusts the exit code of a process that test code can end, or text that test code can print. It also limits the workflow job to an accepted grammar, so any form the invariant cannot read exactly is refused.

Out of scope, judged not worth doing now: the `status` git-call reuse, shard balancing by measured cost, splitting `test_status.Closure`, `Context` as a context manager, and the `sys.path` and encoding cleanups in `support.py`. They are performance or tidiness items with no current defect.

## Revision 2

The first draft was reviewed read-only by the same two reviewers. Both returned "approve with changes". This revision adopts their findings, each checked against unittest's source or by experiment:

- **The workflow invariant was still bypassable.** Quoted keys (`"if": false`, `"continue-on-error": true`) defeated a key blocklist. The job is now checked line by line against an allowlist grammar.
- **A set comparison misses lost repeats.** With an assignment of `[A, A]` and only one run, the sets are equal. Discovery now rejects duplicate ids, and the parent compares counts.
- **One existing case was described inconsistently.** A test that only prints a fake summary now passes. A test that prints one and then calls `os._exit(0)` fails.
- **New false passes through the result file:**
  - `SystemExit(0)` in the last `tearDownClass`/`tearDownModule` runs after every test started. The result file is therefore written only after `TextTestRunner.run` returns normally, never from `stopTestRun` or a `finally`.
  - A `SkipTest` from `tearDownClass`/`tearDownModule` is reported through `addSkip` and keeps `wasSuccessful()` true. It is now a failure.
- **Counting and attribution:**
  - tests covered by a fixture skip are counted in `skipped` once each;
  - `setUpModule` skips are attributed by a class's exact module, not by name prefix;
  - every started test must also have stopped.
- **Implementation notes:** the shard worker puts the repository root on `sys.path`; the verdict reports an unsuccessful run before missing tests; and `complete` is written only after discovery returns.

## Files and components that change

- `scripts/tests/run.py`:
  - **Discovery in a child process.** The parent runs `sys.executable run.py --discover <file>`, with the repository root as the working directory. The child discovers with the same loader. Only after `discover` returns does it write JSON: test ids per `module.Class`, each class's module, the discovery errors, and `"complete": true`. The parent requires all of:
    - exit 0, a readable file and `complete`;
    - no discovery errors;
    - at least one test;
    - no duplicate test id.

    Anything else fails the run with "discovery did not complete", the errors, "no tests found" or "duplicate test id". The parent process never imports test code.
  - **Shards report through a result file.** The parent runs each shard as `sys.executable run.py --shard <file> <ids...>`.
    - The worker inserts the repository root at the front of `sys.path`, loads exactly those ids with `unittest.TestLoader().loadTestsFromName`, and runs them with `unittest.TextTestRunner` writing to stderr, so the human-readable output stays the same.
    - A `TextTestResult` subclass calls `super()` in every hook, so unittest's own accounting and `wasSuccessful()` are unchanged. It also records:
      - the ids passed to `startTest` and to `stopTest`;
      - every skip whose test is not a `unittest.TestCase`, which is a fixture placeholder, with its description.
    - Only after `runner.run(suite)` returns normally does the worker write `{"started": [...], "stopped": [...], "fixture_skips": [...], "failures": n, "errors": n, "skipped": n, "expected_failures": n, "unexpected_successes": n, "successful": bool, "complete": true}`. Here `skipped` counts only skips of real tests. Nothing is written from `stopTestRun` or a `finally` block, so a `SystemExit` anywhere in the run, including a teardown, leaves no result.
  - **The parent's verdict per shard**, checked in this order, with the first failing reason reported:
    1. the process was killed by a signal: "crashed";
    2. there is no result file or it lacks `complete`: "no result";
    3. `successful` is false or the exit code is non-zero: "failed", with the counts;
    4. a fixture skip is anything other than `setUpClass (<module>.<Class>)` for an assigned class or `setUpModule (<module>)` for the module of an assigned class: "unexpected fixture skip";
    5. `started` and `stopped` differ as multisets: "test did not finish";
    6. each assigned id must be started exactly once, or be covered by a fixture skip of its class or its class's exact module and not started. Nothing outside the assignment may be started. Otherwise: "tests not run: ..." or "unexpected tests run: ...".
  - The stderr summary parsing (`RAN`, `STATUS`, `parse`) is removed.
  - The run's last line keeps its form, `OK: ran N tests in K shards (...)` or `FAILED: ...; <reasons>`. N counts started tests plus tests covered by fixture skips, and `skipped` includes the covered tests once each.
- `scripts/tests/test_run.py`:
  - **New cases**, each with a module of at least two tests where counting matters:
    - `load_tests` raising `SystemExit(0)`: exit 1, "discovery did not complete";
    - `os._exit(0)` at import of a test module: exit 1;
    - `sys.exit(0)` at import: exit 1, a discovery error, which already worked;
    - `setUpClass` raising `SkipTest` in a class of two tests: exit 0, `skipped=2`;
    - `setUpModule` raising `SkipTest` in a module of two tests: exit 0, `skipped=2`. A sibling module in the same package that is not skipped still has to run;
    - `setUpClass` raising `RuntimeError`: exit 1, "failed";
    - `tearDownClass` raising `SkipTest`: exit 1, "unexpected fixture skip";
    - `sys.exit(0)` in the last `tearDownClass`: exit 1, "no result";
    - `sys.exit(0)` inside a test: exit 1, an error;
    - a failing `subTest`: exit 1; an `expectedFailure` that fails: exit 0; an unexpected success: exit 1;
    - a test that prints a fake unittest summary to stderr and returns: exit 0;
    - a test that prints one and then calls `os._exit(0)`: exit 1, "no result";
    - a `TestCase.run` override that calls `result.startTest` and returns: exit 1, "test did not finish".
  - **Existing cases** are kept. The ones that asserted the text-parsing messages are changed to the new messages for the same situations:
    - the early `os._exit(0)` shard: "no result";
    - the fake-summary case: split as above.
- `scripts/tests/test_workflow.py`:
  - `control_plane_job_findings` checks every non-blank line of the `control-plane-tests` job block, after `#` comments are removed, against this allowlist:
    - `    runs-on: ubuntu-latest`
    - `    timeout-minutes: <digits>`
    - `    steps:`
    - `      - uses: <owner>/<name>@<40 hex>`
    - `        with:`
    - `          <key>: <value>`, only inside a `uses` step
    - `      - run: <command>`

    The two `run` commands must equal exactly the expected two. Any other line fails, naming the line: a quoted key, `if`, `continue-on-error`, `env`, `shell`, `working-directory`, a continuation line, or a block scalar.
  - Outside the job, the workflow must have no top-level `defaults:`. Its top-level `env:` keys must be exactly `REPO_ARGS` and `VERIFY_ARGS`, because they are inherited by the job.
  - **New mutation cases**, asserted inside the test:
    - an indented continuation `|| true`;
    - `run: |`;
    - `"if": false`;
    - `"continue-on-error": true`;
    - `shell: bash`;
    - a job-level `env:`;
    - a top-level `defaults:` with `run: shell:`;
    - an extra top-level `env:` key `PYTHONPATH`.

No change to `checks.json`, `.github/workflows/repository.yml`, `repo.py`, `guard.py` or `support.py`. The workflow still runs `python3 -m unittest scripts.tests.test_run` and then `python3 scripts/tests/run.py`, so no owner push is needed.

## Order of work

1. `scripts/tests/test_run.py` and `scripts/tests/test_workflow.py`: the new cases. Proof: `python3 -m unittest scripts.tests.test_run scripts.tests.test_workflow` fails on the cases that encode defects 1–3 and the revision's bypasses. The cases that already pass are listed in the commit message.
2. `scripts/tests/test_workflow.py`: the allowlist `control_plane_job_findings`. Proof: `python3 -m unittest scripts.tests.test_workflow` passes.
3. `scripts/tests/run.py`: the discovery child, the shard worker and the parent verdict, with the parsing removed. Proof: `python3 -m unittest scripts.tests.test_run` passes, and `python3 scripts/tests/run.py` passes with the same test count as `python3 -m unittest discover -s scripts/tests -t .`.
4. Full proof (below), then `python3 scripts/repo.py status --change runner-integrity` and `python3 scripts/repo.py verify --change runner-integrity --full`.

## Tests and proof

- **Defects reproduced first:** step 1's new cases fail on the current code for defects 1–3 and for the bypasses this revision names.
- **Same tests, same result:**
  - the runner and `unittest discover` pass with the same count in default, `SDLC_TEST_SUBPROCESS=1` and `SDLC_TEST_EQUIVALENCE=1` modes;
  - `python3 -W error::ResourceWarning scripts/tests/run.py` passes.
- **Sensitivity:** in a scratch copy, the two mutations used for `parallel-tests` (status ok inverted, approve leaking its Context) make the runner exit 1, failing the same tests as `unittest discover`.
- **Speed:** 3 runs at default jobs, median under 15s, the `parallel-tests` target.
- `python3 scripts/repo.py status --change runner-integrity` and `python3 scripts/repo.py verify --change runner-integrity --full` pass.
- **CI:** the pull request's `repository` run on the final head is `success`.

## Risks and mitigations

- **Riskiest step: the parent's verdict (step 3).** It replaces the count check with per-id accounting. Mitigations:
  - the ordered checks above;
  - each early-exit and fixture path has its own test;
  - the full suite must report the same count as `unittest discover`.
- **Fixture placeholders.** Python 3.10–3.13 describe them as `setUpClass (<module>.<Class>)` and `setUpModule (<module>)` (reviewed against CPython's `suite.py`, and observed here on 3.13). A format change would show up as an "unexpected fixture skip", which fails the run rather than letting it pass.
- **Limits that remain:**
  - Test code written to subvert its own runner, for example by forging the result file, is not defended against; review covers that.
  - A suite built by `load_tests` with per-instance state loses that state when shards reload by id. This was already true before this change, and none of this repository's tests do it.
- **The workflow allowlist rejects valid YAML forms.** It is meant to: the job has one accepted spelling. A legitimate future need is a change to this test, reviewed together with the workflow change, which already needs an owner push.

## Rollback or recovery

Open a new change that restores `run.py`, `test_run.py` and `test_workflow.py` from `217fd99`. No other file depends on the result-file format.

## Open questions

None.
