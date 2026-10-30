# Implementation Plan

## Summary

`repo.py close` is meant to require a real, passing verification. A JSON file with no check results passed it, and evidence from a passing run was accepted after the verified file had been changed without committing. Both were reproduced in a scratch fixture. `verify` also prints an absolute evidence path, which `close` writes into `closure.json` when an agent copies it, and `close` hashes any file outside the repository. This change binds evidence to the registered checks and to the files that were verified.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - New function `candidate_digest(root, cid)`: a SHA-256 over the sorted paths and content digests from `git ls-files -co --exclude-standard`. It covers tracked and untracked non-ignored files, reads a symlink as its target text, skips deleted files, and excludes `.evidence/` and `changes/<cid>/closure.json`, so writing the closure does not invalidate its own evidence.
  - `cmd_verify`: compute the digest before running checks, record it as `source.tree_sha256`, and compute it again after the checks. If they differ, mark the run incomplete. Print the evidence path relative to the root when it is inside the root.
  - `evidence_problem`: replace the current result checks. `checks` must be a non-empty list of objects, every check id registered in `checks.json` must appear with status `passed`, and `source.tree_sha256` must equal the current digest. A routed run that leaves a check `not-applicable` is refused, which enforces the existing rule that a full run comes before closing.
  - `closure_record`: an absolute reference inside the root is recorded as a relative path, and a file reference outside the root is refused.
- `scripts/tests/support.py`: `verify_evidence` writes a matching `tree_sha256` by default.
- `scripts/tests/test_approve_close.py`: refused cases for no `checks`, an empty list, non-object items, a missing registered check, a `not-applicable` check, a file changed after verification, a new untracked file after verification and an outside-root reference. Passing cases for an absolute reference inside the root and for writing the closure after verification.
- `scripts/tests/test_verify.py`: `tree_sha256` is recorded, the printed path is relative, and a file changed during a check makes the run incomplete.
- `scripts/tests/test_new.py`: the Quick start test takes the printed evidence path as it is, because `verify` now prints it relative to the root. This line was added in revision 2, after the suite showed that the test assumed an absolute path.
- `changes/README.md`, the "Cite only existing evidence" rule: state the new conditions, including that any file edit after `verify` needs a new `verify`.

## Order of work

1. Write the tests and confirm that the new cases fail on the current code.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Reproduce the fake-evidence and dirty-file cases in a scratch fixture.
5. Run `python3 scripts/repo.py verify --change evidence-binding --full`, then close per `changes/README.md`.

## Tests and proof

The new refused cases fail before step 2 and pass after it. Step 5 is a live proof, because this packet's own `close` must satisfy the new rule.

## Risks and rollback

- **This is not forgery protection.** An agent that hand-writes `evidence.json`, or writes `closure.json` directly, can still produce a matching record. The digest stops stale evidence and accidents. CI re-running the checks and owner review remain the gates.
- **Evidence files from before this change are refused,** because they have no `tree_sha256`. Run `verify` again. Frozen closures are not rechecked.
- **`.evidence/` must stay out of the digest.** It is excluded by name, including when a repository removes it from `.gitignore`.
- **`--evidence-dir` elsewhere in the tree** could change the digest. `close` then asks for a new run, which fails safe.
- **Run time:** each `verify` and `close` hashes the tracked files. This template's tree is small, and hashing grows with repository size.
- Rollback: a new change that restores the previous checks.

## Out of scope

- Validating evidence in `status` or CI. `.evidence/` is not in the candidate tree.
- Publishing local evidence from CI, which would need a workflow change.
- Malformed `checks.json` shapes.
- Routing that forces a full run when `checks.json` changes.
