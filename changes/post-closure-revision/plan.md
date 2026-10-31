# Implementation Plan

## Summary

The v2.2.0 reviews found, and a scratch fixture confirmed, a deadlock. A pull request needs a candidate closure, so review or CI can ask for a material change while the closure exists. Changing `plan.md` or `write_scope` then needs a new approval, but `approve` refuses any change with a closure, and `close` refuses a stale approval. Two status problems also mislead an agent that revises a plan. A stale plan during implementation adds `not-ready`, which reads as an order to undo the work. Re-approving `spec.md` leaves `out-of-order` until `plan.md` is re-approved, and nothing says so.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `approval_claim`: refuse only when the change has an anchor on the baseline branch, matching `closure_record`. An unmerged closure no longer blocks an approval. No `reopen` command is added: `close` already rewrites a candidate closure.
  - `check_order`: do not add `awaiting-approval` when the open artifact already has a `stale-approval` reason. The change stays blocked by that error, and `check_scope` no longer adds `not-ready`.
  - `check_order`: the timestamp `out-of-order` message says to re-approve the later artifacts.
  - `cmd_approve`: when downstream claims exist, print that they must be approved again, in order.
- `scripts/tests/test_approve_close.py`: approval is refused on a frozen change and allowed on a candidate; the full revision flow on a closed branch: edit `plan.md`, approve, `verify --full`, `close`, and `status` reports a current candidate. The same flow for a widened `write_scope`. `approve` prints the downstream notice.
- `scripts/tests/test_status.py`: a stale plan with implementation changes reports `stale-approval` and not `not-ready`; a plan that was never approved with implementation changes still reports `not-ready`; a re-approved `spec.md` still blocks until `plan.md` is re-approved.
- `changes/README.md`, "Fixes after closure": add the material revision order: revise the artifact or `write_scope`, owner approves in chain order, merge a changed carried artifact into the root, `verify --full`, `close`, commit.

## Order of work

1. Write the tests and confirm the new cases fail: `python3 -m unittest scripts.tests.test_approve_close scripts.tests.test_status`.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Repeat the scratch reproductions for the deadlock and for the two status messages.
5. Run `python3 scripts/repo.py verify --change post-closure-revision --full`, then close per `changes/README.md`.

## Tests and proof

The new cases fail before step 2 and pass after it. The revision flow test runs the real commands, so it proves the deadlock is gone.

## Risks and rollback

- **The closure stays on disk during a revision.** Until `close` runs again, `status` reports it invalid or stale, and pull-request CI fails. That is the intended signal. It cannot merge in that state.
- **Weaker signal for an unapproved revision?** No. A stale approval is still an error and blocks readiness. Only the extra `not-ready` and `awaiting-approval` reasons go away, and only for a stale artifact.
- **Owner approval is still a claim.** Under Codex nothing stops an agent from running `approve` itself. This change does not alter that, and an approval that replaces an earlier one leaves no trace in the final diff.
- **Scope edits under Claude Code:** the guard denies a file-tool edit to `write_scope` after plan approval, so that agent still needs the owner or an approved shell write. Left for a later change.
- **Rollback:** before merge, drop the branch. After merge, open a new change.
