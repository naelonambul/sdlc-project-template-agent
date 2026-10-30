# Implementation Plan

## Summary

Two independent reviews found that a literal Quick start cannot finish `product-init`. `repo.py new` creates an empty `write_scope`, so copying the approved `intent.md` and `spec.md` into the root fails with `out-of-scope`, and widening the scope makes the plan approval stale. This was reproduced in a scratch fixture. The reviews also found that the `repository-quality` skill tells an agent to add a CI job, while the GitHub App cannot push `.github/workflows/**`. This change fixes both before the Codex solo test.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`, `new_packet_files`: after the packet files are known, add each carried root artifact (`intent.md`, `spec.md`) to `write_scope`, without duplicates. This covers `product-init`, `intent`, `behavior` and `--with-spec`. `check_scope` does not change, so the root destination stays an explicit, approval-bound part of the scope.
- `scripts/tests/test_new.py`: tests that a `product-init` packet's scope contains both root files, that a `--with-spec` packet contains `spec.md` only, that a `repository` packet gains nothing, and that a pattern passed by hand is not duplicated. One end-to-end test runs `new`, three `approve` calls, the root copy, `verify` and `close`, then asserts that `status --change` exits 0 with `ok: true`.
- `README.md`, Quick start `product-init` step: say that `new` adds the carried root files, and that `--scope` must list every other path the change will touch, including `checks.json`, before the plan is approved, because the approval binds the scope.
- `changes/README.md`, the Scope rule: the same statement in one sentence.
- `.agents/skills/sdlc-artifacts/SKILL.md`, step 3: say that a packet made without `repo.py new` must list the carried root files itself.
- `.agents/skills/repository-quality/SKILL.md`, next to the CI job instruction: the App cannot push `.github/workflows/**`, so a new check group or CI job is an owner handoff. Stop and ask the owner to push the workflow change, and do not revert the group to silence `checks-unwired`. A check that runs with Python and Git alone can use the `core` group.
- `docs/agent-surfaces.md`: one probe row, required because a skill changes.

## Order of work

1. Write the tests and confirm that they fail on the current code.
2. Change `new_packet_files`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Edit the documents and skills.
4. Run the smoke probe in a scratch copy and record it.
5. Run `python3 scripts/repo.py verify --change quickstart-init-fix --full`, then close per `changes/README.md`.

## Tests and proof

The new tests fail before step 2 and pass after it. The end-to-end test is the proof that the Quick start path reaches a valid candidate closure.

## Risks and rollback

- An agent could now change a root artifact through a `behavior` or `intent` packet's scope, but those kinds exist to do that, and the root copy must still equal the approved carried artifact at `close`.
- Packets that are already open keep their stored scope and are unaffected.
- Rollback: revert the squash commit.

## Out of scope

- Other findings from the two reviews. They go to `closure-integrity`, `pr-finalization`, `evidence-binding` or a later release.
- Changing the App's permissions.
- The order of Quick start steps 2 and 3.
