# Implementation Plan

## Summary

A derived project's post-merge CI (PodoBank run 41743584316, `verify-core`, Git 2.56) failed once in `RepoCase.setUp`: `shutil.copytree(_template(), self.root)` raised `FileNotFoundError` for `.git/objects/maintenance.lock`. A rerun passed.

The cause is Git's automatic maintenance. `git commit` ends by starting `git maintenance run --auto --quiet --detach` (seen with `GIT_TRACE=1`). That process takes `objects/maintenance.lock` before it detaches, and it removes the lock after `commit` has already returned. `_template()` returns right after its `commit`, and `setUp` starts copying at once. So the copy can list the lock and then fail to open it. Fixture commits made later in a test (`RepoCase.commit`) start the same process, which races the equivalence-mode snapshot (`run_both`) and the `tearDown` cleanup in the same way.

The fix turns off automatic maintenance for every fixture repository. Copies are not made tolerant of missing files, and lock files are not skipped: ignoring locks would hide a copy taken while Git was writing.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/tests/support.py`:
  - `GIT_ENV` gains `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=maintenance.auto`, `GIT_CONFIG_VALUE_0=false`. `DEFAULT_GIT_ENV` is copied from it as now, so the template, `RepoCase.git`, `run_subprocess` and `invoke` all get it. `scripts/tests/__init__.py` removes inherited `GIT_CONFIG_COUNT` at import, and that happens before any of these are used, so the two do not conflict.
  - `_template()` runs `git config maintenance.auto false` right after `git init`. Every test repository is a copy of the template, so a Git command that does not pass `GIT_ENV` is covered as well.
- `scripts/tests/test_status.py`: the direct `git clone` in `test_shallow_history_blocks_closure` passes `env={**os.environ, **support.GIT_ENV}`, like every other fixture Git call.
- `scripts/tests/test_support.py`: a regression test class (see Tests and proof).

## Order of work

1. Add the regression tests to `scripts/tests/test_support.py` and confirm they fail on the base: `python3 -m unittest scripts.tests.test_support -v`.
2. Change `scripts/tests/support.py` and `scripts/tests/test_status.py`, then rerun step 1's command and confirm it passes.
3. Run the whole suite in the default mode and in equivalence mode: `python3 -m unittest discover -s scripts/tests -t .` and `SDLC_TEST_EQUIVALENCE=1 python3 -m unittest discover -s scripts/tests -t .`.
4. Run `python3 scripts/repo.py verify --change fixture-git-maintenance --full`, then close per `changes/README.md`.

## Tests and proof

The race cannot be forced reliably, because it depends on timing. The proof is that no fixture Git command starts maintenance at all:

- In a `RepoCase` test, run `self.commit(...)` with `GIT_TRACE` pointing at a file, and assert the trace has no `maintenance run` line. On the base the trace shows `git maintenance run --auto --quiet --detach`, so this test fails before step 2.
- Assert `git config --get maintenance.auto` in `self.root` prints `false`, without `GIT_ENV`, so the template's local setting is what is checked.

The full and equivalence-mode suites stay green. No `AGENTS.md`, skill or guard file changes, so no smoke probe is required.

## Risks and mitigations

- **Tests set `GIT_CONFIG_COUNT`.** A later test that patches `GIT_ENV` with its own `GIT_CONFIG_*` entries would replace this one. No test does that today (`BatchedReadsUnderHostileConfig` patches only `GIT_CONFIG_GLOBAL`), and the template's local `maintenance.auto false` still covers it.
- **Production behaviour is unchanged.** Only `scripts/tests` changes. `repo.py` and `guard.py` are not touched, and maintenance on real repositories still runs as the user has configured it.
- **Derived projects** pick this up through their next template sync. PodoBank is the first.

## Rollback or recovery

Open a new `repository` change that removes the three `GIT_CONFIG_*` entries, the `git config` call and the clone's `env`, and deletes the regression tests. No stored data changes.

## Open questions

None.
