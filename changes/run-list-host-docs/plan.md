# Implementation Plan

## Summary

Issue #38 asks that `agent-gh` expose read-only `run list`, with no logs, and that the host setup documentation describe the command and its restrictions. The owner has applied the wrapper change on this host. `docs/host-setup.md` still tells hosts to cover run logs, which contradicts the issue. This change corrects that paragraph.

This is a `repository` change: one documentation paragraph. It changes no `scripts/**`, `checks.json`, `.github/**`, or lifecycle semantics.

### Decisions

- **The wrapper exposes no logs.** The owner's issue #38 says so, and the owner applied that patch. This replaces the `ci-log-identity` advice to have a wrapper cover read-only run logs. The closed packet stays as it is.
- **The owner still supplies failed lines.** "When CI is red" in `sdlc-artifacts` already says to ask the owner when the path exposes no run logs, so the skill does not change.

### Evidence

Checked on this host on 2026-11-01. `agent-gh run list --branch main --limit 3` returned push runs with workflow name, event, branch, commit SHA, status, conclusion and URL. `agent-gh run view 1` was refused with `only 'run list' is allowed`.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `docs/host-setup.md`: the paragraph starting "Have `agent-gh` cover".

### Text for `docs/host-setup.md`

Replace:

```markdown
Have `agent-gh` cover `pr checks`, read-only `run list` and read-only run logs, which the App's Actions permission allows. Otherwise the owner has to confirm the post-merge `push` run and supply the failed lines when CI is red.
```

with:

```markdown
Have `agent-gh` cover `pr checks` and read-only `run list`, so the agent can confirm the post-merge `push` run. Allow `run list` only with `--branch`, `--commit`, `--event` and `--limit`, and fix its output to workflow name, event, branch, commit SHA, status, conclusion and URL, so the `event` field tells a `push` run from a pull-request run. Refuse every other `run` command: `agent-gh` exposes no job logs, reruns or cancels, and no workflow changes. The App's Actions permission could read logs, but the wrapper does not offer them, so the owner supplies the failed lines when CI is red. A wrapper without `run list` leaves the owner to confirm the `push` run too.
```

## Order of work

Each step is one coordinator edit, so the route is single agent.

1. Edit `docs/host-setup.md`. Proof: `grep -c 'exposes no job logs' docs/host-setup.md` prints `1`, and `grep -c 'read-only run logs' docs/host-setup.md` prints `0`.
2. Commit, run `python3 scripts/repo.py verify --change run-list-host-docs --full`, then close per `changes/README.md`.
3. Open the pull request with `Closes #38`.
4. After merge, confirm the `push` run with `agent-gh run list`.

## Tests and proof

- `python3 scripts/repo.py status --change run-list-host-docs` passes, which shows every changed path is inside `write_scope`.
- `python3 scripts/repo.py verify --change run-list-host-docs --full` reports no `failed`, `blocked`, or `not-run` check.
- Step 4 is the live proof of #38's first acceptance criteria.
- No smoke test: this change touches neither `AGENTS.md`, a skill, nor the guard.

## Risks and mitigations

- **An adopter wants logs on their wrapper.** The paragraph states this template's host policy; a host can decide otherwise outside this repository.

## Rollback or recovery

Before merge, drop the branch. After merge, open a new change that restores the paragraph.

## Open questions

None.
