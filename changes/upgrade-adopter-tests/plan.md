# Implementation Plan

## Summary

PR #57 added `Completeness` tests to `scripts/tests/test_upgrade.py`. They check invariants of the template repository itself:

- every `UPGRADE_COPY`/`UPGRADE_MERGE` entry is tracked;
- `owned-files.txt` equals the tracked copy-group files;
- every new `status` error code is named in `migrations.md`;
- every `migrations.md` heading names a `changes/<id>/` packet.

`scripts/tests/` is in the copy group, so these tests ship to every repository built on the template, where they do not hold. A dry run of the first real upgrade (dogtailor-v3, base `51ca588`, target `8e3ce0d`) failed exactly one of 276 tests: `test_every_migration_heading_names_a_change_packet`, because the template's packets are never copied. The other three fail in other adopters:

- the manifest test, when an adopter keeps its own files under a copy directory (`local` in the report);
- the error-code test, when a carried `repo.py` adds a code;
- the listed-path test, when an adopter has no file in the merge group.

Inside an adopter, the `template` pin already covers what these tests protect: the digest binds the owned files and the manifest.

The fix runs the `Completeness` class only in the template itself. The template is the repository whose `checks.json` has no `template` pin. An adopter has one once it has upgraded. One that has not yet recorded a pin is mid-upgrade, and its `status` reports that.

## Files and components that change

- `scripts/tests/test_upgrade.py`:
  - a function `template_itself(root)` that returns false when `root/checks.json` holds a `template` key, and true otherwise;
  - `Completeness` is skipped with a reason when it returns false;
  - tests for the function on a fixture with and without a pin.
- `.agents/skills/template-upgrade/SKILL.md`: one sentence in "Close" saying that the template's own completeness tests are skipped once the pin is recorded.

## Order of work

1. Add `template_itself` and the skip; add its two tests. Proof: `python3 -m unittest scripts.tests.test_upgrade` passes in the template. On a scratch copy of the dogtailor dry run (pin recorded, this file copied in), `python3 scripts/tests/run.py` reports no failure and shows the `Completeness` tests as skipped.
2. Skill sentence. Proof: `python3 scripts/tests/run.py`.
3. Verify. `python3 scripts/repo.py status --change upgrade-adopter-tests` and `python3 scripts/repo.py verify --change upgrade-adopter-tests --full`.

## Tests and proof

- The two new tests fail against a version that always returns true.
- Full suite, `status` and `verify --full` in the template.
- The dogtailor dry run, rerun with the fixed file and the pin recorded: no test failure.

## Risks and mitigations

- **A pinned template would silently skip its own invariants.** The template never records a pin in its own `checks.json`. The skip reason names the condition, so the skip is visible in test output.
- **An adopter mid-upgrade, with no pin yet, still runs the tests.** That is the window before the pin is recorded. The skill records the pin as part of the same change.

## Rollback or recovery

Revert the squash commit.

## Open questions

None.
