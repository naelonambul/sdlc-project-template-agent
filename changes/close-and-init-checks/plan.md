# Implementation Plan

## Summary

Two gaps let a change look finished when it is not. Both were reproduced on main at 9a4f975:

1. **`repo.py close` accepts any non-empty evidence string.** `--evidence "made-up-ref"` with `verify` never run produced a candidate closure and later a frozen packet.
2. **Placeholder `product-init` artifacts can be approved.** Copies of the root `intent.md` and `spec.md` that still carry the unestablished marker can be approved, closed and frozen. The root stays unestablished, and the next `new --kind behavior` is refused.

The change makes `close` require one passing `verify` run for this change at the current commit, and refuses placeholder artifacts at `approve` and in `status`.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `closure_record` calls a new `check_verify_evidence(root, cid, refs)`. At least one `--evidence` reference must be a readable JSON file that satisfies all of the following. Otherwise `close` refuses and names the first problem it found.
    - `change` equals the change id.
    - `complete` is true.
    - No check has status `failed` or `blocked`.
    - `source.commit` equals `HEAD`.
  - Other references stay allowed as extra free-form evidence, such as a link or a path outside Git, and are recorded as today.
  - `approval_claim` refuses `intent.md` or `spec.md` of a `product-init` change while the file contains the unestablished marker.
  - `evaluate_change` adds the error `placeholder-artifact` when a `product-init` change has an approval on an artifact that contains the marker, unless `st.closure == "frozen"`. This catches a claim written by hand.
- `scripts/tests/support.py`: a helper that writes a valid evidence file.
- `scripts/tests/test_approve_close.py`: the existing `close` cases cite that helper, and the new cases below are added. The refusal cases keep their assertions.
- `scripts/tests/test_status.py`: the `placeholder-artifact` cases.
- `changes/README.md`: the Closure section and evidence rules state the new requirement.

## Order of work

1. Add the helper and the new failing tests, leaving existing cases as they are. Proof: `python3 -m unittest scripts.tests.test_approve_close scripts.tests.test_status` fails only on the new tests.
2. Change `closure_record` and move existing `close` cases to the helper. Proof: `python3 -m unittest scripts.tests.test_approve_close` passes.
3. Change `approval_claim` and `evaluate_change`. Proof: `python3 -m unittest scripts.tests.test_status scripts.tests.test_approve_close` passes.
4. Update `changes/README.md`. Proof: `grep -n "source.commit\|HEAD" changes/README.md` matches the new rule.
5. Repeat the original reproductions in a scratch clone: `close --evidence made-up-ref` and approval of an unedited `product-init` copy are both refused. Proof: both exit 1.
6. `python3 scripts/repo.py status --change close-and-init-checks` and `python3 scripts/repo.py verify --change close-and-init-checks --full` pass, then close with the new rule in force.

## Tests and proof

`close` refuses when:

- the only reference is free text, or a missing file;
- the file is not JSON, or not a JSON object;
- `change` names another change;
- `complete` is false;
- a check is `failed` or `blocked`;
- `source.commit` is not `HEAD`.

`close` succeeds when a valid file is cited alone, and with an extra free-form reference, which is recorded unchanged. A rewrite after a fix needs fresh evidence.

Placeholder cases:

- `approve` refuses `intent.md`, and `spec.md`, while they contain the marker, and accepts them once it is gone.
- A hand-written claim on a marked artifact gives `placeholder-artifact` and `readiness=blocked`.
- A frozen `product-init` packet with the marker stays `frozen`.
- Other kinds are unaffected.

## Risks and rollback

- **Riskiest step: requiring `source.commit == HEAD`.** A commit made between `verify` and `close` makes `close` refuse. That matches the documented order, in which `close` follows the last verification, and the fix is one `verify` rerun.
- **This is still friction, not proof.** An agent can write a fake `evidence.json`, and evidence is not committed, so CI cannot check it. CI still runs the checks independently, and that stays the authority. The closure records the file's digest.
- **`verify` must run with the change identified.** Without `--change`, on a branch with no `change/<id>` name, `change` can be empty and `close` refuses. The message names `--change`.
- **Existing projects.** Closures already written are not re-checked, because only `close` applies the rule. Open changes need a passing `verify` before closing, as the documentation already says.
- Rollback: revert the squash commit.

## Out of scope

- Validating evidence in `status` or CI.
- Detecting a working tree changed after `verify`. `source.dirty` is normally true at this point, because the packet is not committed yet.
- `AGENTS.md`, the skills and `docs/`, whose wording stays correct.
