# Implementation Plan

## Summary

The owner runs this repository alone. The `agent-evals` GitHub Actions workflow added by `enforcement-layers` only does work when an `ANTHROPIC_API_KEY` secret exists, and the owner has decided not to register one. Without the secret the workflow produces a "not run" notice on every pull request that touches agent configuration and every Monday, which is noise with no signal. This change deletes the workflow and removes every reference to it and to the secret from the documentation.

The evals themselves stay. `scripts/evals.py` and `evals/` remain a local, on-demand diagnostic that uses the operator's own Claude Code login. `AGENTS.md`, `scripts/README.md`, `docs/agent-surfaces.md` and the `sdlc-artifacts` skill describe them that way already and need no change.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `.github/workflows/agent-evals.yml`: deleted.
- `docs/host-setup.md`: remove the section "Optional: credentials for the agent evals".
- `docs/adoption.md`: drop `agent-evals.yml` from the adoption scope command, the optional-layers note, the per-file copy list, and the upgrade re-merge list.
- `README.md`: the `evals/` control-plane bullet says the evals are run locally on demand, not by CI; the template-releases paragraph no longer mentions the secret.
- `evals/README.md`: the "CI" section is replaced by a short "Not run in CI" section explaining that evals are a local tool and when to run them.

No Python, test, check-registry or `repository.yml` change. `scripts/tests/test_evals.py` keeps its test that `ANTHROPIC_API_KEY` passes through the harness environment allowlist, because a local operator may still authenticate that way.

## Order of work

1. Delete `.github/workflows/agent-evals.yml`. Proof: `git ls-files .github/workflows` lists only `repository.yml`.
2. Edit the four documents listed above. Proof: `grep -rn "agent-evals\|ANTHROPIC_API_KEY" --exclude-dir=changes --exclude-dir=.git .` matches only `scripts/tests/test_evals.py`.
3. Run `python3 scripts/repo.py verify --change remove-evals-workflow` and `--full`. Proof: both pass; `status` reports `readiness=ready` and no out-of-scope path.

## Tests and proof

- `python3 scripts/repo.py verify --change remove-evals-workflow --full` (control-plane tests, 157 cases).
- The grep in step 2.
- `python3 scripts/repo.py status` reports `status: ok` and no `hook-broken` or workflow finding, since `repository.yml` is untouched.

No eval run is needed: the change touches no `AGENTS.md`, skill, guard or `evals/` case, only `evals/README.md`.

## Risks and mitigations

- **A downstream template consumer wanted the CI evals.** Release notes for the next tag say the workflow was removed and that the `enforcement-layers` packet (frozen at `449e4e2`) still contains it for anyone who wants to restore it.
- **Docs drift.** The step 2 grep is the acceptance check; the reviewer reruns it.

## Rollback or recovery

Revert the squash commit. The workflow file and the documentation paragraphs return unchanged; no state outside git is involved.

## Open questions

None.
