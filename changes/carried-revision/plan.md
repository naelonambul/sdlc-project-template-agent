# Implementation Plan

## Summary

The second Codex test found a deadlock that PR #28 did not cover. After closure, the owner re-approved a revised carried `spec.md` and `plan.md`, and `changes/README.md` said to replace the root next. But `status` stayed `readiness=blocked`, and `AGENTS.md` bars changes outside the packet until `ready`. Codex correctly stopped. Two causes: `check_baseline` compares the recorded baseline with the branch's root, which already holds the previous approved copy, so it reports a false `stale-baseline`; and a closure that is merely out of date counts as a blocker for readiness. The same comparison hides a real stale baseline: when `main` moves, a carried artifact copied to the root passes.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `check_baseline`: for a carried artifact, judge freshness and establishment against the baseline branch's file, because the change itself replaces the root copy on its branch. Uncarried artifacts keep reading the root. When the baseline branch is not resolvable, it falls back to the root.
  - `evaluate_change`: `closure-invalid`, `closure-stale` and `closure-unmerged` no longer block `readiness`. They stay errors, so `status` still fails and a pull request cannot pass. `readiness` then means what `changes/README.md` says: approvals are current and work may proceed.
- `scripts/tests/test_approve_close.py`: the full revision flow for a carried `spec.md` on a closed `behavior` change: revise, approve `spec.md` and `plan.md`, `readiness=ready`, replace the root, implement, `verify --full`, `close`, and a current candidate.
- `scripts/tests/test_status.py`: no `stale-baseline` during that revision; a real `main` move reports `stale-baseline` for a carried artifact copied to the root; a `product-init` packet copied to the root passes; a stale approval with a closure stays blocked.
- `changes/README.md`: Freshness says a carried artifact is compared with the baseline branch, and the revision rule says `readiness` returns to `ready` once approvals are current, while `status` fails until `close` runs.

## Order of work

1. Write the tests and confirm they fail: `python3 -m unittest scripts.tests.test_approve_close scripts.tests.test_status`.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Repeat the reproduction from the second Codex test in a scratch fixture.
5. Run `python3 scripts/repo.py verify --change carried-revision --full`, then close per `changes/README.md`.

## Tests and proof

The new cases fail before step 2 and pass after it. The revision test uses a carried `spec.md`, the case the earlier `repository` fixtures missed. No `AGENTS.md`, skill or guard file changes, so no smoke probe is required.

## Risks and rollback

- **`readiness=ready` with an invalid closure:** this state is new. `status` still exits 1, and the pull-request gate still needs a candidate closure, so it cannot merge.
- **A branch behind a moved baseline now reports `stale-baseline`** for a carried artifact. That is correct, and the author must reconcile it. It adds friction only when two changes alter the same baseline.
- **`check_baseline` reads Git on each open packet.** It reads at most two files per packet.
- **Rollback:** before merge, drop the branch. After merge, open a new change.
