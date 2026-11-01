# Implementation Plan

## Summary

The agent must work under its own identity, but the template only says "the host's wrapper if it has one". It does not say which commands to use on a given host. This change states the rule: the identity is required, and the command path follows from the host's state.

- If plain `git` and `gh` are already the agent identity, the agent uses them.
- If they are the owner's login, the agent uses `agent-git` and `agent-gh`.
- If neither is available, the agent stops and asks the owner. It never falls back to the owner's credentials.

This is a `repository` change: guidance text only. It changes no `scripts/**`, `checks.json`, `.github/**`, or lifecycle semantics.

### Decisions

- **Owner decision, 2026-11-01:** a wrapper exists for hosts where the owner's account is on plain `git` and `gh`, because it reduces the permissions the agent works with. A host already configured with the bot uses plain commands.
- **This reverses one decision in `ci-log-identity`:** "No wrapper name in the template." The template now names `agent-git` and `agent-gh` as the conventional names for this path. They stay optional, and the template does not ship them. The closed packet stays as it is.
- **Setup does not force a wrapper.** A host with the bot on plain commands does not need one.
- **Policy text comes first.** The CI identity check, the repository settings and the `agent-gh` file are separate work. The App cannot push `.github/workflows/**`, and the wrapper lives outside this repository.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `AGENTS.md`: one rule under "Working rules".
- `docs/host-setup.md`: a new "Which commands the agent uses" subsection in "The agent's identity", replacing the sentences after "The token helper is host-specific and lives outside the repository."
- `.agents/skills/sdlc-artifacts/SKILL.md`: one clause of "When CI is red".
- `docs/agent-surfaces.md`: smoke-test result rows.

### Text for `AGENTS.md`

Add under "Working rules", before the delegation rule:

```markdown
- Commit, push, open pull requests and read CI under the agent identity, using the command path `docs/host-setup.md` selects for this host. If no path works, stop and ask the owner. Never fall back to the owner's credentials.
```

### Text for `docs/host-setup.md`

Keep "The token helper is host-specific and lives outside the repository." Replace the three sentences after it, starting at "If it wraps `gh`", with:

```markdown
### Which commands the agent uses

Every commit, push, pull request and CI read runs under the agent identity. Before the first of these in a session, the agent checks `git config user.name` and `gh auth status`, then takes the first row that matches:

| Host state | Commands |
|---|---|
| Plain `git` and `gh` are already the agent identity | plain `git` and `gh` |
| Plain `git` or `gh` is the owner's login, and `agent-git` and `agent-gh` are on `PATH` | `agent-git` and `agent-gh` |
| Neither | stop and ask the owner to set one up; never use the owner's credentials instead |

The wrappers are for a host where the owner's login stays on plain `git` and `gh`. The owner's setup does not change, and the agent works with a token limited to one repository that expires within an hour. These are the conventional names for this path, not required installs: a host whose plain commands are already the agent identity needs neither, and the template does not ship them.

Have `agent-gh` cover `pr checks`, read-only `run list` and read-only run logs, which the App's Actions permission allows. Otherwise the owner has to confirm the post-merge `push` run and supply the failed lines when CI is red.

This is a rule for the agent, not a control. Nothing here stops a session from using the owner's login, so `repo.py approve` claims, the required checks and the owner's review stay the gates.
```

### Text for `sdlc-artifacts`

In "When CI is red", replace:

```markdown
run them through the host's wrapper if it has one (`docs/host-setup.md`). If the wrapper does not expose run logs, ask the owner for the failed lines.
```

with:

```markdown
run them through the command path `docs/host-setup.md` selects for this host. If that path does not expose run logs, ask the owner for the failed lines.
```

## Order of work

Each step is one coordinator edit, so the route is single agent.

1. Edit `AGENTS.md`. Proof: `grep -c 'Never fall back to the owner' AGENTS.md` prints `1`.
2. Edit `docs/host-setup.md`. Proof: `grep -c 'Which commands the agent uses' docs/host-setup.md` prints `1`.
3. Edit `.agents/skills/sdlc-artifacts/SKILL.md`. Proof: `grep -c 'command path `docs/host-setup.md` selects' .agents/skills/sdlc-artifacts/SKILL.md` prints `1`.
4. Run the smoke-test procedure in `docs/agent-surfaces.md` and add the result rows. Proof: 4/4 core skills in each new row.
5. Run `python3 scripts/repo.py verify --change agent-identity-policy --full`, then close per `changes/README.md`.

## Tests and proof

- `python3 scripts/repo.py status --change agent-identity-policy` passes, which shows every changed path is inside `write_scope`.
- `python3 scripts/repo.py verify --change agent-identity-policy --full` reports no `failed`, `blocked`, or `not-run` check.
- The smoke test confirms `AGENTS.md` and skill discovery, because this change touches both.
- This is advisory text, so no check proves agents follow it.

## Risks and mitigations

- **`gh auth status` may not identify an App token clearly.** That would send a bot-configured host to the "neither" row. The cost is a question to the owner, not a wrong identity, so the rule stays safe. Revise the check if a host hits this.
- **The text promises commands the wrapper lacks.** `agent-gh` on this host admits no `run` command yet. The text is a host requirement and states the fallback. Issue #38 tracks the host work.
- **Adopters carry their own wrapper wording.** Podobank has a local edit near "When CI is red", so a sync may need a hand merge.

## Rollback or recovery

Before merge, drop the branch. After merge, open a new change that restores the three text blocks.

## Open questions

- Issue #38 asks that `agent-gh` expose no logs, while this text keeps read-only run logs from `ci-log-identity`. This change keeps the current text. If the owner forbids logs on the wrapper, a later change removes that clause.
