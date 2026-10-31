# Implementation Plan

## Summary

The v2.2.0 reviews found, and a scratch fixture confirmed, that closure evidence is checked only when `close` runs. After that, a commit that changes product code keeps its closure and passes pull-request `status`. Four related gaps are fixed here. `verify` exits 0 after printing `INCOMPLETE: files changed during the run`. The evidence digest ignores file modes, so `chmod +x` after `verify` passes `close`. It skips submodule commits. An ignored file inside a packet produces a closure that fails in a clean clone.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `CLOSURE_KEYS`: add `tree_sha256`.
  - `validate_closure`: when `tree_sha256` is present, it must be a sha256 digest. It stays optional here, so frozen closures remain valid.
  - `check_candidate_closure`: a candidate must carry `tree_sha256` equal to `candidate_digest(root, id)`. Otherwise it reports `closure-stale`, naming `repo.py verify` and `repo.py close`, and saying to update the branch first if it is behind the baseline.
  - `closure_record`: write `tree_sha256`, computed after `check_verify_evidence` has shown that it equals the evidence digest.
  - `candidate_digest`: hash each path with its mode: `120000` with the link target, `100755` or `100644` from the executable bit, and `160000` with the commit from `git ls-files -s`.
  - `worktree_packet`: list files with `git ls-files -co --exclude-standard` under the packet, and read a symlink as its target, so it matches `tree_packet`.
  - `cmd_verify`: return 1 when `stable` is false. Partial `--group` runs keep exit 0.
- `scripts/tests/support.py`: `close` writes a matching `tree_sha256`.
- `scripts/tests/test_status.py`: a committed code edit after closure fails pull-request `status`; a frozen closure without `tree_sha256` passes; a refreshed closure passes; an ignored packet file does not change the packet digest; a symlink in a packet digests the same in the worktree and at a commit.
- `scripts/tests/test_approve_close.py`: `close` writes `tree_sha256`; a mode change after `verify` is refused; a change between a regular file and a symlink is refused.
- `scripts/tests/test_verify.py`: the unstable run asserts a nonzero exit; a submodule commit changes the digest.
- `scripts/tests/test_new.py`: adjusted only if its Quick start flow depends on the old closure content.
- `changes/README.md`: the closure example and evidence rules, including the required order for fixes after closure: edit, `verify --full`, `close`, commit.

## Order of work

1. Write the new tests and confirm they fail: `python3 -m unittest scripts.tests.test_status scripts.tests.test_approve_close scripts.tests.test_verify`.
2. Change `scripts/repo.py` and `scripts/tests/support.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Repeat the scratch reproductions for a code edit after closure, an unstable run, a mode change and an ignored packet file.
5. Run `python3 scripts/repo.py verify --change closure-tree-binding --full`, then close per `changes/README.md`.

## Tests and proof

The new cases fail before step 2 and pass after it. This packet's own `close` and pull request are a live proof that real CI accepts the new field, because CI recomputes the digest on a fresh checkout.

## Risks and rollback

- **CI checks the pull request's merge ref.** On a branch that is behind the baseline, that tree differs from the closed tree, so `status` reports `closure-stale`. This is intended: the combined tree was never verified locally. The fix is to update the branch, verify and close again. A project that requires up-to-date branches already needs the update. It costs one more push after every base change.
- **Open candidates must close again** after upgrading, because they have no `tree_sha256` and the digest format changes.
- **Files a project generates without ignoring them** now fail `verify` and can make a closure stale in CI. Add them to `.gitignore`.
- **`--evidence-dir` inside the tree** now exits 1, because writing there changes the files during the run. The default `.evidence/` and paths outside the tree are unaffected.
- **Not forgery protection.** An agent can still compute and write a matching digest without running the checks. CI re-running them and owner review remain the gates.
- **Frozen closures are not rechecked.** The tree at the anchor may include other changes, and history already protects it.
- **Rollback:** before merge, drop the branch. After merge, open a new change. A plain revert of the closing commit is refused.
