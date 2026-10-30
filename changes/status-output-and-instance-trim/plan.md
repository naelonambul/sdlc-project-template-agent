# Implementation Plan

## Summary

Two costs grow with no benefit to an agent working on a change:

1. **`repo.py status` prints every packet in full.** Each packet costs about 290 bytes, and `--change <id>` does not narrow it. At 14 packets a call prints 4 KB, all of it read back into agent context, and it grows with every merged change.
2. **Projects created from the template inherit its 14 closed packets.** They account for about 248 KB of the 276 KB under `changes/`, describe the template's history rather than the project's, and add noise to every search of the repository.

This change folds healthy frozen packets into one line of the text output, and adds a step to the Quick start that removes the template's packets from a new project.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`, `print_status`: a packet is folded when it is not the active change, its `closure` is `frozen`, and it has no reasons. Folded packets print as one line, `frozen: <count>`, after the detailed packets. Every other packet prints exactly as today. `compute_status`, the `--json` output, the failure lines, and evaluation of every packet do not change, so integrity checking keeps full coverage.
- `scripts/tests/test_status.py`: new text-output tests.
- `README.md`: a new Quick start step between steps 1 and 2:

  ```sh
  find changes -mindepth 1 -maxdepth 1 -type d ! -name _template -exec git rm -rq {} +
  git commit -m "Remove the template's closed change packets"
  git push origin main
  ```

  It states that the step runs before `main` is protected, because it commits directly to `main`, and that the push is part of the step: until then `status` compares against `origin/main` and reports the deletions as several touched packets.

## Order of work

1. Add failing tests to `scripts/tests/test_status.py`. Proof: `python3 -m unittest scripts.tests.test_status` fails only on the new tests.
2. Change `print_status`. Proof: `python3 -m unittest scripts.tests.test_status` passes, and `python3 scripts/repo.py status --change status-output-and-instance-trim | wc -c` is under 1000 on this repository.
3. Add the Quick start step. Proof: run the exact commands in a scratch clone with a local bare `origin`, then `python3 scripts/repo.py status` reports `status: ok` and `python3 -m unittest discover -s scripts/tests -t .` passes there.
4. `python3 scripts/repo.py status --change status-output-and-instance-trim` and `python3 scripts/repo.py verify --change status-output-and-instance-trim --full` pass, then close per `changes/README.md`.

## Tests and proof

New cases, driving `repo.py status` in text mode:

- Two frozen packets and no active change print `frozen: 2` and neither packet's detail.
- The active change prints in full even when it is frozen.
- A frozen packet with a reason (a `warn` or `info` reason, if a case can produce one) prints in full.
- A frozen packet whose bytes changed after its anchor is no longer `frozen`, so it prints in full and `status` fails.
- With no frozen packets, no `frozen:` line appears.
- `--json` still lists every packet.

Already proven by hand on main at a6c5f30, in a scratch clone with a bare origin: after the removal and push, `status` is ok locally and with `--ci --branch=`; `verify --full` and the 145 tests pass in a trimmed clone; `_template` and `changes/README.md` stay.

## Risks and rollback

- **Riskiest step: hiding a problem by folding.** The fold condition requires no reasons and `closure == "frozen"`, and failures still print from `result["failures"]`, so nothing that fails `status` is hidden.
- **A reader wants a frozen packet's detail.** `--json`, or `--change <id>`, still shows it.
- **The Quick start step is run after `main` is protected.** The push is refused, and nothing is lost. The project keeps the packets or removes them through a pull request.
- **A project that skips the step** works as before.
- Rollback: revert the squash commit.

## Out of scope

- Reducing the number of git calls, and the `repo.py` cleanup, which are later changes.
- Changing `--json`, or `status --change` evaluating every packet.
- `docs/host-setup.md`, `changes/README.md` and existing projects such as `dogtailor-v3`.
