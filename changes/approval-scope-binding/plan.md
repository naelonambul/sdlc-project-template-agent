# Implementation Plan

## Summary

Two gate holes were reproduced on main at 9a4f975:

1. **`write_scope` is not bound to approval.** After the plan is approved, adding `**` to `write_scope` keeps `readiness=ready` and `status: ok`, and the guard allows the edit, because the approval digest covers `plan.md` only. The owner-approved scope can be widened without the owner.
2. **A shell comment hides the rest of a multi-line command from the guard.** `tokenize` turns newlines into ` ; ` and then `shlex` treats `#` as a comment to the end of the whole string. `# note` + newline + `git reset --hard` returns `allow`, as do `git push --force`, `repo.py approve` and a redirect into `change.json` in the same position. This contradicts `scripts/hooks/README.md`, which says multi-line commands are inspected.

The change binds the plan approval to the digest of `write_scope`, and makes the guard strip comments line by line.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - `APPROVAL_KEYS` gains `write_scope_sha256`; a new `scope_digest(scope)` hashes the canonical JSON of the sorted pattern list, so reordering is not a change.
  - `approval_claim` records `write_scope_sha256` on `plan.md` claims. `plan.md` is the last artifact of every chain, so one binding covers every kind.
  - `evaluate_change`: a `plan.md` claim whose `write_scope_sha256` differs from the current scope adds `stale-approval`. After `check_closure`, a current `plan.md` claim without the field adds the error `unbound-scope` unless `st.closure == "frozen"`.
  - Both messages name the fix: re-run `repo.py approve <id> plan.md`, which already replaces the claim without any artifact edit.
- `scripts/hooks/guard.py`:
  - `decide_path`: when the current `change.json` has a `plan.md` approval, a proposed `write_scope` that differs (compared sorted) is denied with `change-scope`.
  - `tokenize`: a new `strip_shell_comments` walks the command tracking single quotes, double quotes and backslashes. Outside quotes, a `#` at the start of a word drops text up to the newline, and a newline becomes ` ; `. `lexer.commenters` is set to empty so `shlex` cannot remove anything further.
- `scripts/tests/support.py`: `approve` writes the new field, as `repo.py approve` does.
- `scripts/tests/test_status.py`, `test_approve_close.py`, `test_guard.py`: new tests below.
- `scripts/hooks/README.md`: states the comment handling and the new `change-scope` denial.
- `changes/README.md`: Approval claims section shows the field and says when it is required. `changes/_template/` changes only if it needs to.
- `docs/agent-surfaces.md`: records the probe run, which is required when the guard changes.
- `docs/host-setup.md`: line 7 says "its own GitHub App identity" without naming one host's account. The guide is what projects created from the template follow: the GitHub App account opens pull requests and the owner's account reviews them.

## Order of work

1. Add failing tests first, on the unchanged code. Proof: `python3 -m unittest scripts.tests.test_guard scripts.tests.test_status scripts.tests.test_approve_close` fails only on the new tests.
2. Change `scripts/repo.py` and `scripts/tests/support.py`. Proof: `python3 -m unittest scripts.tests.test_status scripts.tests.test_approve_close` passes.
3. Change `scripts/hooks/guard.py`. Proof: `python3 -m unittest scripts.tests.test_guard` passes.
4. Update `scripts/hooks/README.md`, `changes/README.md` and `docs/host-setup.md`. Proof: `grep -n write_scope_sha256 changes/README.md` matches and `git grep -n mini26 -- docs` finds nothing.
5. Run the probes in `docs/agent-surfaces.md` and record the result there. Proof: a new dated row exists in its table.
6. `python3 scripts/repo.py status --change approval-scope-binding` and `python3 scripts/repo.py verify --change approval-scope-binding --full` pass, then close per `changes/README.md`.

## Tests and proof

New `repo.py` cases:

- Widening `write_scope` after approval gives `stale-approval`, `readiness=blocked`, and a non-zero `status`.
- Reordering the same patterns stays `ready`.
- Re-running `approve plan.md` after a scope change returns to `ready`, with no artifact edit.
- `approve` records the field on `plan.md` and not on `intent.md` or `spec.md`.
- A current claim without the field is blocked with `unbound-scope` on an open packet.
- A frozen packet without the field stays `frozen`. All 13 existing frozen packets stay `status: ok`, with no packet byte changed.

New guard cases, each expecting `ask`:

- A comment line followed by `git reset --hard`, `git push --force origin main`, `python3 scripts/repo.py approve x plan.md`, and `echo x > changes/x/change.json`.
- A comment containing an apostrophe (`# don't`) before `git reset --hard`.
- A trailing comment on the first line (`echo start # note`) before the destructive line.
- The same comment forms inside `bash -c '...'`.

New guard cases, each expecting `allow`:

- `echo a#b` and `git log --grep '#1'`, which must not be treated as comments.
- A quoted multi-line argument with a `#` in it, such as `git commit -m` with a body.
- A comment that only mentions a destructive command.

Path cases: widening `write_scope` after plan approval is denied; editing it before approval, and reordering it after, are allowed.

## Risks and rollback

- **In-flight packets downstream.** An open packet approved before this change blocks with `unbound-scope` until the owner re-approves `plan.md`. This is deliberate: an old claim says nothing about scope. Frozen packets are unaffected. There is no such packet in this repository's main.
- **A closed but unmerged packet** also needs re-approval, and `close` must be rerun because `packet_sha256` covers `change.json`.
- **Riskiest step: the comment scanner.** It is a partial shell lexer. Heredoc bodies are not recognised, so an apostrophe in one leaves the quotes unbalanced and `tokenize` falls back to `command.split()`, as it already does. Text in a heredoc can also cause an extra `ask`. Both fail towards asking; neither can produce a new `allow` that the current code denies or asks about, and the test list above pins that.
- **A scope change during implementation** now needs the owner again. That is the point of the change, and the cost is one `approve` command.
- Rollback: revert the squash commit. Claims written with the field fail `invalid-approval` on the old code, so any packet approved in between needs that one key removed.

## Out of scope

- Other guard gaps (`bash -lc`, `git branch --delete --force`, `git restore .`, `git checkout -- .`), the `echo git reset --hard` false positive, and the hook matcher for MCP edit tools.
- Evidence validation in `close`, and approving placeholder `product-init` artifacts.
- Host settings on GitHub. They are per repository: this template repository stays as it is, and each project created from the template is configured by `docs/host-setup.md`.
- Account names inside frozen packets, which are never edited.
