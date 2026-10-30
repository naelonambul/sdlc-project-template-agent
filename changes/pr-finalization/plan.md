# Implementation Plan

## Summary

`changes/README.md` says that a closure comes before the pull request and that one pull request is one change, but CI enforces neither. Using the CI form of `status`, an unapproved packet-only pull request passed, and so did an approved one without a closure. A packet whose scope covers `changes/**` can also carry a second, unapproved packet. The first two were reproduced in a scratch fixture, and an independent review reproduced the third. This change makes the pull request mode of `status` the final gate.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`, `compute_status`: when `--pr-body` is passed and an active change is identified, add two failures:
  - the active packet's closure is not `candidate`;
  - the diff touches a packet other than the active one, meaning a path `changes/<other>/...` where `<other>` is not the active id and not `_template`.

  The mode is keyed on `--pr-body`, which CI already passes, so `.github/workflows/repository.yml` does not change and the owner does not need to push a workflow edit. Local `status` without `--pr-body` stays permissive for drafting.
- `scripts/tests/test_status.py`:
  - In pull request mode, an unapproved packet, an approved packet without a closure, and a packet with an invalid closure each fail.
  - A pull request with a valid candidate closure passes.
  - A second packet inside the first packet's scope fails.
  - An edit to `changes/_template/` within scope passes.
  - The same drafting states still pass locally without `--pr-body`.
  - Existing identity tests that use `--pr-body` keep their assertions and gain a closure where they assert success.
- `changes/README.md`: the Pull request bullet states both rules, and the Lifecycle table's step 6 row says that the CI `status` job fails without a candidate closure.

## Order of work

1. Write the tests and confirm that the new cases fail on the current code.
2. Change `compute_status`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit `changes/README.md`.
4. Reproduce the three cases in a scratch fixture with the CI form of `status`.
5. Run `python3 scripts/repo.py verify --change pr-finalization --full`, then close per `changes/README.md`.

## Tests and proof

The new failing cases fail before step 2 and pass after it. The drafting tests show that local status did not get stricter. This packet's own pull request is a live proof, because it runs the new gate on a real candidate closure.

## Risks and rollback

- **Draft pull requests stay red until the closure is pushed.** A plan-only pull request is no longer possible. Agents push claims to the branch and open the pull request after closing, which is what the Lifecycle already says.
- **`verify` is not changed.** It does not call `compute_status`, so the CI `verify-core` job behaves as before.
- **`--pr-body` used locally** gets the same stricter result. That is intended, because it reproduces CI.
- Rollback: a new change that removes the two failures.

## Out of scope

- Using `.github/workflows/repository.yml` or a new flag.
- A base-branch policy that runs `status` from trusted code. The candidate still controls `repo.py`, and owner review remains the gate.
- Duplicate identical `Change-ID` lines.
- Evidence checks. They go to `evidence-binding`.
