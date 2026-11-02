# Implementation Plan

## Summary

Make the control-plane test suite (`scripts/tests`, the `control-plane` check) faster without changing what any existing test asserts; revision 2 sets the target from measurement (see "Measured during implementation"). Most of its time goes to starting a new Python process for every `repo.py` and `guard.py` call and to building a fresh Git repository in every `setUp`. This change runs those calls in-process, keeps a small always-on subprocess contract suite for both entry points, and copies a prebuilt fixture repository instead of building one.

This is a `repository` change. Product code changes in one place only: `approval_claim` and `closure_record` in `scripts/repo.py` close the `Context` they open, as `compute_status` already does. That is resource cleanup with no change to any output, exit code, or file `repo.py` writes. No `scripts/hooks/guard.py`, `checks.json`, `.github/**`, existing test assertion, or dependency changes. The suite stays standard-library Python that needs only Git.

### Measurements

Taken on 2026-11-03 on an Apple M4 (10 cores) with Git 2.54.0 and Python 3.13.13, at `33e5064`:

- The full suite: 261 tests in 71.6s on this run (45s in an earlier, less loaded run). `test_status` is the largest module, then `test_approve_close`, then `test_guard`.
- The tests call `repo.py` through `RepoCase.run_repo` or `RepoCase.status` about 160 times, and `guard.py` through `GuardCase.run_guard` in every guard test.
- `RepoCase.setUp` (`git init`, three files, one commit): about 20ms; copying a prebuilt repository: about 4ms.
- `python3 -c pass` costs 8.8ms here; `guard.py claude` for a Bash call costs 33ms.

### Measured during implementation (revision 2)

The first approved revision assumed one in-process `status` call costs about 20ms. That premise was wrong, and its "under 25s" target with it. Measured on the same machine after steps 1-3, with the fixture template and in-process `run_repo`:

- The default suite: 261 tests in 46s, all passing; `SDLC_TEST_EQUIVALENCE=1`: 261 tests in 103s, all passing.
- Per module: `test_status` 23.9s, `test_approve_close` 8.9s, `test_guard` 5.6s (still subprocess), `test_verify` 4.8s, `test_new` 2.4s.
- `cProfile` of `test_status`: 20.6s of 23.6s in `subprocess.run`. 133 in-process `status` calls take about 98ms each, spent in about 13 `git` processes per call at about 8ms each (`repo.git()`: 1,766 calls, 14.7s); fixture setup through `RepoCase.git` spends about 5.9s. Removing the Python start saves about 9ms per call, not 70ms.
- So a sequential suite stays near 40s whatever this change does in the test harness. Reaching 25s needs a parallel runner, which is the next change.

The owner chose to finish this change on its approved scope and take the parallel runner next, after a second read-only review by the same two models recommended exactly that sequence.

### Review

Before approval the draft was reviewed read-only by Codex (`gpt-6-astra`) and Antigravity (`gemini-4-argon-high`). Both returned "approve with changes". This revision adopts their findings, each checked against the code: `approve` and `close` leave a `git cat-file --batch` process open (`repo.py:1467`, `repo.py:1578`); no guard test would run `guard.py` as a process; guard's parser has no `prog` (`guard.py:433`); equivalence needs `duration_seconds` (`repo.py:1058`) and traceback handling, must run in place because tests pass absolute and parent-directory paths, and must compare files written as well as output; the planned sensitivity mutations were not pinned by any assertion and could not fail the equivalence comparison; and `BatchedReadsUnderHostileConfig` patches `support.GIT_ENV` before `setUp`, which must not reach the shared template.

### Rejected options

- **Reordering `claude_decision` in `guard.py` so a Bash call skips `find_root`.** It would change behaviour: today a Bash command outside any Git repository is allowed with "no repository", and after the reorder it would be judged by `decide_command`.
- **Lazy imports in `guard.py`.** `-X importtime` shows `argparse` is the only import the `claude` path could skip, about 1-2ms of 33ms.
- **`functools.lru_cache` on `glob_regex` in `repo.py`.** `status` already runs in 0.1-0.2s; no measurable gain.
- **Keeping `approve` and `close` as subprocess calls to avoid touching `repo.py`.** It leaves the slowest tests slow and keeps a real leak hidden; closing the `Context` is smaller and correct.
- **A parallel test runner.** The only way below about 40s, but it changes the registered `control-plane` argv in `checks.json`, which CI runs, and mixing it with the in-process harness would blur which change caused a failure. The next change, measured from this one.
- **Fewer `git` processes in `repo.py status`** (sharing `merge-base`/diff between `resolve_active` and `check_scope`, one `ls-files`, `git show` through `Objects`). Estimated at 3-9s across the suite, so the sequential suite would still exceed 30s, and it touches status and closure evaluation, which would need a differential check against the previous implementation like `status-batching`'s; the in-process/subprocess equivalence cannot prove it, because both sides run the same product code.
- **Removing the duplicate unittest job in CI.** A workflow policy decision for the owner, and a separate change.
- **Rewriting `repo.py` or the guard in another language.** The cost is process starts and Git calls, not Python computation, and the template promises "Python 3 and Git only".

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`: in `approval_claim` and `closure_record`, wrap the code after `ctx = Context(...)` in `try: ... finally: ctx.close()`. Nothing else.
- `scripts/tests/support.py`:
  - **Fixture template.** `DEFAULT_GIT_ENV = dict(GIT_ENV)` is captured at import. The first `setUp` in a process builds the initial repository once, under `DEFAULT_GIT_ENV`, into a module-level temporary directory removed with `atexit`. Every `setUp` copies it with `shutil.copytree(template, self.root, symlinks=True)`. A test that patches `GIT_ENV` (such as `BatchedReadsUnderHostileConfig`) still gets that patch for every later call, and cannot change the template.
  - **`invoke(module, script, argv, cwd, stdin)`**, one in-process runner shared by `repo.py` and `guard.py`. For the call only, it:
    - `os.chdir(cwd)`, because `repo_root()` and `find_root()` read the working directory;
    - applies the current `GIT_ENV` with `unittest.mock.patch.dict(os.environ, ...)`, because both scripts' `git` calls inherit the environment;
    - sets `sys.argv = [str(script), *argv]`, so argparse's `prog` matches a real run even where the parser does not fix it;
    - replaces `sys.stdout` and `sys.stderr` with `io.TextIOWrapper(io.BytesIO(), encoding="utf-8")`, strict for stdout and `backslashreplace` for stderr, matching Python's streams on a UTF-8 pipe, so text a pipe could not encode still fails; `sys.stdin` becomes `io.StringIO(stdin)` when input is given and is left alone otherwise, as a subprocess inherits it;
    - calls `module.main(argv)`; a returned `int`, or a `SystemExit` code with `None` as 0, becomes `returncode`; any other exception becomes `returncode` 1 with `traceback.format_exc()` on stderr;
    - restores the directory, environment, `sys.argv` and the three streams in `finally`, and returns `subprocess.CompletedProcess(argv, returncode, stdout, stderr)` with decoded text.
  - **`run_repo(*args, cwd=None)`** keeps its signature and return type, so no call site changes, and uses `invoke`. **`run_repo_subprocess`** is today's implementation, unchanged.
  - **Modes.** `SDLC_TEST_SUBPROCESS=1` makes `run_repo` use the subprocess path. `SDLC_TEST_EQUIVALENCE=1` makes it run every call both ways, in place:
    1. snapshot the test's whole temporary directory (`self._tmp.name`, which holds the repository and any sibling directory a test writes to) with `copytree(symlinks=True)`;
    2. run the subprocess path and record its result and the post-call state of that directory: every path, its type, mode, symlink target, and content digest, with `.git/` limited to refs, `HEAD` and `index`;
    3. restore the directory from the snapshot, at the same path, so absolute paths, `..` paths and `cwd` values in arguments and payloads stay valid;
    4. run the in-process path, record the same, compare, and return the in-process result with its state left in place.
  - **`compare_runs(a, b)`**, a pure function: equal `returncode`; equal `stdout` and `stderr` after normalization; equal post-call state after normalization. Normalization is exactly: `duration_seconds` values in JSON output and evidence files; `verify` run ids and the evidence directory names derived from them; the `at` field `approve` writes; and, when stderr contains a Python traceback, comparison of its last line (exception type and message) instead of the frames, because the outermost frames differ by construction. Any other difference fails with both values shown.
- `scripts/tests/test_guard.py`: `GuardCase.run_guard` keeps its signature and uses `invoke(guard, GUARD, ...)` with the given stdin; the same two environment variables select the subprocess or equivalence path.
- `scripts/tests/test_support.py` (new):
  - **Subprocess contract tests, always on**, so both entry points keep running as real processes in the default suite: `repo.py status --json --ci` on a fixture; `repo.py approve` refused (exit 1, message on stderr); `repo.py` with an unknown subcommand (argparse exit 2 and its `usage: repo.py` line); `guard.py path` deny (exit 2) and allow (exit 0); `guard.py command` ask (exit 3); `guard.py claude` with a Bash payload on stdin; and the hook command string from `.claude/settings.json`, run as written with a deny payload. Each asserts the same result through `invoke`, so the contract and the in-process path are tied.
  - **Comparator tests**: `compare_runs` passes for identical runs and for runs differing only in each normalized field, and fails for a changed exit code, an extra stdout key, an extra stderr line, a changed traceback last line, a changed file content, mode, or symlink target, and an extra file.
  - **No leaked state**: after `invoke` returns, normally or through each exception path, the working directory, `os.environ`, `sys.argv` and the three streams equal their values before the call, and no `git cat-file` child of the test process is still running.

The existing tests that start processes themselves (`test_new.py` running a lone copy of `repo.py`, `test_verify.py` checking the test package's environment) are untouched.

## Order of work

Single agent: the steps share `support.py`. Each step is one commit.

1. **Close the `Context`** in `approval_claim` and `closure_record`. Prove: `python3 -m unittest discover -s scripts/tests -t .` passes unchanged.
2. **Fixture template.** Prove: the full suite passes, and `python3 -m unittest scripts.tests.test_status.BatchedReadsUnderHostileConfig` passes when run alone.
3. **`invoke`, in-process `run_repo`, modes, and `compare_runs`**, with `test_support.py`. Prove: `SDLC_TEST_EQUIVALENCE=1 python3 -m unittest discover -s scripts/tests -t .` passes with no equivalence failure.
4. **In-process `run_guard`.** Prove: `SDLC_TEST_EQUIVALENCE=1 python3 -m unittest scripts.tests.test_guard scripts.tests.test_support` passes.
5. **Sensitivity and timing**, as Tests and proof describes. No commit unless a finding needs one, which would be a plan revision.
6. Run `python3 scripts/repo.py verify --change test-speedup --full`, then close per `changes/README.md`.

## Tests and proof

- **Same results.** The full suite passes in default (in-process), `SDLC_TEST_SUBPROCESS=1`, and `SDLC_TEST_EQUIVALENCE=1` modes. All 261 existing tests remain, none is skipped, removed or loosened, and the new tests are in `test_support.py` only. `git diff --stat` touches only `write_scope`.
- **Equivalence.** The equivalence run compares the output and post-call files of every `repo.py` and `guard.py` call made by the suite and reports zero differences.
- **Comparator sensitivity.** The comparator tests above show `compare_runs` catches a one-sided difference in each compared dimension, which equivalence between two identical scripts cannot show by itself.
- **Suite sensitivity.** In a scratch copy of the repository, never the working tree, apply one mutation at a time and run the suite there in default mode and in `SDLC_TEST_SUBPROCESS=1` mode: invert `ok` in `status --json`; make `main` return 2 on `Refusal`; write a wrong `packet_sha256` in `closure_record`; change the `root-baseline` deny reason in `guard.py`. Each must fail at least one existing test, and the same tests in both modes. A mutation no existing assertion catches is replaced by one that an existing assertion pins, and the substitution is recorded in the pull request.
- **No leaked processes.** The default suite runs with `-W error::ResourceWarning` without new warnings, and the leak test in `test_support.py` passes.
- **Speed.** In one session on the machine above, run the default suite three times at `33e5064` and three times at the finished change, alternating. The median of the finished change, with all existing and new tests, is under 50s. Report every run and the range. Timing on CI is not a success criterion.
- The 46s and 261 passes measured after step 3 are not evidence for steps 3-4 as a whole: `test_support.py` and the guard paths are proven only by the runs above, made after step 4.
- `python3 scripts/repo.py verify --change test-speedup --full` reports no `failed`, `blocked`, or `not-run` check.

No `AGENTS.md`, skill, or guard file changes, so no smoke probe is required.

## Risks and mitigations

- **Riskiest step: step 3.** An in-process call can pass where a process would fail. Mitigations: `repo.py` and `guard.py` keep no module-level mutable state today (checked at `33e5064`); every call gets its own `Context`; directory, environment, `sys.argv` and streams are set and restored per call; the contract tests keep both entry points running as processes; and equivalence mode compares every call's output and files against a real process.
- **Shared `sys.path`.** In-process, `scripts/` and `scripts/hooks/` are both importable, so an accidental cross-import would pass in-process. The subprocess contract tests run each script with only its own directory on the path and would fail.
- **A future `repo.py` may add module-level state** that leaks between in-process calls. `SDLC_TEST_EQUIVALENCE=1` catches it; it is not registered as a check because it more than doubles the suite's runtime.
- **`os.chdir` and `sys.argv` are process-wide.** The tests are single-threaded. A later parallel runner must use processes, not threads.
- **Shared template.** Tests write only to their own copy; the template is built from `DEFAULT_GIT_ENV` and never handed to a test.
- **Equivalence restore.** Restoring the temporary directory between the two runs replaces the repository at the same path; a test holding an open file handle across a `run_repo` call would see a stale handle. None does today, and an equivalence failure would show it.

## Rollback or recovery

Before merge, drop the branch. After merge, set `SDLC_TEST_SUBPROCESS=1` to fall back without a code change, or open a new change that restores the four files. No data, packet, or closure format changes.

## Open questions

None.
