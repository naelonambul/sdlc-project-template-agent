# Implementation Plan

## Summary

The v2.2.0 reviews found instructions that send an agent into a failure on later changes. Nothing says to start the next change from the updated baseline, and a branch that is behind fails with `frozen packet removed from the candidate`, which names the wrong problem. `AGENTS.md` and `repository-quality` allow a routed `verify`, which `close` refuses. Two files say a CI-blocked local check is acceptable, but a blocked check fails CI. Two files claim rebase merges work, and a rebase after a closure refresh fails `frozen-integrity`. `changes/README.md` says closure evidence can be matched against CI evidence, and it cannot. Most of this was read from the files. The behind-branch and rebase cases were reproduced in a scratch fixture.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`, `compute_status`: the `frozen packet removed from the candidate` failure adds that the branch may be behind the baseline.
- `scripts/tests/test_status.py`: a branch behind the baseline gets that message.
- `AGENTS.md`, Definition of done: `repo.py verify --change <id> --full` before closing.
- `.agents/skills/repository-quality/SKILL.md`: before closing, run `--full`, which `close` requires.
- `.agents/skills/sdlc-artifacts/SKILL.md`, Start a change: fetch and branch `change/<id>` from the updated baseline before `repo.py new`.
- `changes/README.md`:
  - Lifecycle step 1: the same rule.
  - Closure: the evidence digest records the local file. CI uploads its own independent evidence, so the two are not matched.
  - Anchor: remove the rebased-commit claim.
  - Undo: a new change that restores files uses a kind that carries `spec.md` when the undone change altered the baseline, and a plan's rollback must say this, not "revert".
- `docs/host-setup.md`, Merge policy: squash merges and merge commits work. Rebase merges do not, once a closure has been refreshed.
- `.agents/skills/verification-map/SKILL.md` and `references/platforms.md`: a check CI cannot host is not registered in `checks.json`, because `close` needs every registered check passed and CI fails on `blocked`. Keep the script in the repository, run it locally and cite the result in the pull request.
- `docs/agent-surfaces.md`: a product test that creates its own Git fixtures must clear `GIT_DIR` and `GIT_WORK_TREE`, since `verify` passes the environment through. Add the smoke-test rows.

## Order of work

1. Write the test and confirm it fails: `python3 -m unittest scripts.tests.test_status`.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit the documents and skills.
4. Run the smoke procedure in `docs/agent-surfaces.md` on a scratch copy with Claude Code and Codex, because `AGENTS.md` and skills changed. Add the rows.
5. Run `python3 scripts/repo.py verify --change later-change-docs --full`, then close per `changes/README.md`.

## Tests and proof

The new test fails before step 2 and passes after it. The smoke probe proves that `AGENTS.md` and the skills are still delivered.

## Risks and rollback

- **`verify` keeps passing `GIT_DIR` to checks.** Removing it would break a product check that runs Git in a repository whose data is outside the worktree, so this stays a documented rule.
- **A project with an uncheckable platform loses the registered local check.** Its proof becomes a pull-request citation and owner review, which matches what `close` and CI actually allow.
- **Frozen plans still say "revert the squashed commit".** They cannot be edited. The Undo section is the current rule.
- **Rollback:** before merge, drop the branch. After merge, open a new change.
