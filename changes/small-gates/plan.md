# Implementation Plan

## Summary

The v2.2.0 reviews found five small gaps, all confirmed in a scratch fixture except the nested-type crashes, which were reported by one reviewer and confirmed by reading the code. A `repository` change can erase an established baseline by adding the unestablished marker, because the rule reads the candidate's file. Two identical `Change-ID` lines pass, although a repeated ID is documented to block. A commented `repo.py verify --group web` line satisfies the group wiring check. Malformed `checks.json`, a non-string baseline digest, and an unhashable check id crash `repo.py` with a traceback, and a check script without the executable bit crashes `verify` before it writes evidence.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - New function `established_at(ctx, commit, name)`: reads the file at the base commit and reports whether it lacks the unestablished marker. `check_scope` uses it, so the rule follows the base, not the candidate.
  - `parse_pr_change_ids`: keep every match, so repeated lines count as several IDs.
  - `load_config`: on invalid JSON or a non-object, return a value that `validate_checks` reports as a problem. `status` then shows `checks-invalid`, and `verify` shows `blocked`.
  - `check_baseline`: format a declared digest with `str()`, so a non-string value reports `stale-baseline`.
  - `validate_checks`: add an id to `seen` only after it is a valid string.
  - `run_check`: require the executable bit for a path-relative tool, and turn an `OSError` from `Popen` into a `blocked` result.
  - `config_findings`: ignore comments when reading group wiring from the workflow.
- `scripts/tests/test_status.py`: marker on an established root refused; marker on an unestablished root still allowed; identical repeated `Change-ID` refused; malformed and non-object `checks.json`; non-string baseline digest; unhashable check id; commented group line reports `checks-unwired`.
- `scripts/tests/test_verify.py`: malformed `checks.json` reports `blocked`; a non-executable check reports `blocked` and evidence is written.

## Order of work

1. Write the tests and confirm they fail: `python3 -m unittest scripts.tests.test_status scripts.tests.test_verify`.
2. Change `scripts/repo.py`, then run `python3 -m unittest discover -s scripts/tests -t .`.
3. Repeat the scratch reproductions for the marker, repeated ID, comment wiring, malformed configuration and non-executable check.
4. Run `python3 scripts/repo.py verify --change small-gates --full`, then close per `changes/README.md`.

## Tests and proof

The new cases fail before step 2 and pass after it. No document changes: each change makes the code match what is already documented. No `AGENTS.md`, skill or guard file changes, so no smoke probe is required.

## Risks and rollback

- **Repository changes during setup:** a baseline that is unestablished at the base can still be reshaped, as before.
- **`config_findings` reads comments by line.** A `#` inside a quoted workflow value, after a space, would cut that line. The form it looks for does not use one.
- **`test_workflow.py` keeps its own regex.** It is out of scope, and this repository's workflow has no such comment.
- **A malformed `checks.json` on the baseline branch** falls back to `main` as the baseline branch while `status` reports the error.
- **Rollback:** before merge, drop the branch. After merge, open a new change.
