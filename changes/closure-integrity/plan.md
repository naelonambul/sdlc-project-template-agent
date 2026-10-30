# Implementation Plan

## Summary

Frozen packets are the audit record, but only a packet that still has its `closure.json` is checked. Deleting a frozen closure reopens the packet as `readiness=ready`, and deleting a whole frozen packet makes it disappear from `status`. Both pass the CI status command. Separately, after Quick start step 2 removes the template's packets, a new change that reuses one of their ids fails `frozen-integrity`, because the anchor search finds the deleted packet's closure in history. All three were reproduced in a scratch fixture.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `find_closure_anchor`: return `None` when the closure is not on the tip of the baseline branch, and otherwise return the newest commit that introduced it. A closure deleted from the baseline branch then no longer anchors a new packet with the same id.
  - New function `removed_frozen(ctx)`: list `changes/<id>/closure.json` on the tip of the baseline branch with `git ls-tree`, and return the ids whose `closure.json` is missing from the candidate working tree. It returns nothing when the baseline branch is unresolvable or history is shallow, where existing checks already block closures.
  - `compute_status`: add one `frozen-integrity` failure for each returned id, whichever change is active.
- `scripts/tests/test_status.py`:
  - Deleting a frozen closure fails, in both the local and the CI form of `status`.
  - Deleting a whole frozen packet from another change's scope fails.
  - A deletion already committed on the baseline branch passes. This is Quick start step 2.
  - A new packet that reuses a deleted id reaches a valid candidate closure, and then freezes after merge.
  - `test_candidate_closure_is_valid_before_merge`: use branch `change/init` and assert `ok`, because today it hides an identity failure.
- `changes/README.md`, the frozen rule: a closed packet stays on the baseline branch. Removing it fails `status`, so a pull request cannot do it, including a plain `git revert` of the closing squash commit. To undo a merged change, open a new change that restores the files. Quick start step 2 is the only exception, and it commits to the baseline branch before protection.

## Order of work

1. Write the tests and confirm that the new cases fail on the current code.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Reproduce the three cases in a scratch fixture with the CI form of `status`, and confirm that the new `closure-integrity` packet itself passes.
5. Run `python3 scripts/repo.py verify --change closure-integrity --full`, then close per `changes/README.md`.

## Tests and proof

The new tests fail before step 2 and pass after it. Step 4 repeats the original reproduction outside the test suite.

## Risks and rollback

- **`git revert` of a merged change now fails `status` in a pull request.** This is deliberate, and the README states the replacement. Older plans that name "revert the squash commit" as rollback now mean a new change that restores the files.
- **Quick start step 2:** before the push, `status` already fails, as the README says. It keeps failing until the push, now with an added frozen message. After the push, the tip has no closures and `status` passes.
- **Run time:** one extra `git ls-tree` per `status`.
- Rollback: a new change that restores the previous behavior, as above.

## Out of scope

- Deleted packets outside the tip of the baseline branch, such as a packet removed and merged in an unprotected repository. `status` on `main` cannot see them.
- A closure in a pull request that has none. That goes to `pr-finalization`.
- `--head` reading the working tree.
