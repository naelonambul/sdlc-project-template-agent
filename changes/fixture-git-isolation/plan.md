# Implementation Plan

## Summary

The Codex solo test on a repository from this template found three problems. With `GIT_DIR` and `GIT_WORK_TREE` set, as in a Git hook or a Codex sandbox workaround, the control-plane fixtures operate on the caller's real Git data: running `scripts.tests.test_new` that way produced 30 failures and errors and created `refs/heads/change/init` in the real data. The README says `status` "reports" removed packets, when it fails. The docs do not say that Codex `workspace-write` leaves `.git` read-only.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/tests/__init__.py`: on import, remove from `os.environ` every name printed by `git rev-parse --local-env-vars`. These are the variables that point Git at a repository. The fixture helpers and the direct `git clone` in `test_status.py` all inherit `os.environ`, so one removal covers them, and new tests are covered too.
- `scripts/tests/test_verify.py`: a test that imports `scripts.tests` in a subprocess with `GIT_DIR` and `GIT_WORK_TREE` set and confirms both are gone.
- `README.md`, Quick start step 2: say that `status` fails with `frozen packet removed from the candidate` until the deletion is pushed, and that this is expected.
- `docs/agent-surfaces.md`, Codex section: state that `workspace-write` keeps `.git` read-only, so Codex cannot commit in a plain clone, and give the owner's options: run commits outside the sandbox, or keep the Git data outside the worktree, add it as a writable root and set `GIT_DIR` and `GIT_WORK_TREE`.

## Order of work

1. Add the test and confirm it fails.
2. Change `scripts/tests/__init__.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Repeat the reproduction in a scratch clone with the Git data outside the worktree. Confirm the suite passes and the ref list is unchanged.
4. Edit the two documents.
5. Run `python3 scripts/repo.py verify --change fixture-git-isolation --full`, then close per `changes/README.md`.

## Tests and proof

The new test fails before step 2 and passes after it. Step 3 is the live proof against the original failure. No `AGENTS.md`, skill or guard file changes, so no smoke probe is required.

## Risks and rollback

- **Only `scripts/tests` is covered.** A derived project's own tests that create Git fixtures can still inherit these variables. Its checks are its own, and this change does not alter how `verify` runs them.
- **The removal is process-wide,** but it runs only when the test package is imported, never in `repo.py`.
- **Git is now required at test import.** The suite already needs Git in every fixture.
- **Rollback:** revert the squashed commit. No stored data changes.
