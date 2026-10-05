# Implementation Plan

## Summary

Documentation only. Three things the `enforcement-layers` change (#9) left out or exposed:

1. **Who pushes what.** Merging #9 was blocked by the ruleset's "approval from someone other than the last pusher": the owner had recorded the approval and the closure locally and pushed them, so the owner was both the pull-request author and the last pusher, and nobody could approve. The host setup guide describes the review modes but not the sequence that avoids this. The owner resolved it by removing the ruleset, so the repository now runs in the single-person, shared-identity mode without saying so.
2. **Adoption of the enforcement layers.** `docs/adoption.md` lists the files an existing repository copies from a release and does not yet name `scripts/hooks/`, `scripts/evals.py`, `evals/`, `.claude/settings.json` or `.github/workflows/agent-evals.yml`, so an adopter following it would not get the guard or the evals.
3. **Eval credentials.** The advisory `agent-evals` workflow needs an `ANTHROPIC_API_KEY` repository secret and otherwise only prints a notice. Nothing tells the host administrator to add it.

No code, tests, checks or packets other than this one change.

## Files and components that change

| Path | Change |
|---|---|
| `docs/host-setup.md` | New subsection "Who pushes what" under Review modes: the observed failure, the pull-request-author rule, the recommended sequence per mode. The `ANTHROPIC_API_KEY` secret as an optional one-time step. Trust mode: say explicitly what shared identity plus no ruleset means and record it. |
| `docs/adoption.md` | Add the enforcement-layer files to the copy-verbatim list, the adoption `--scope` command, the hand-merge notes (`.claude/settings.json`), the upgrade diff list; note that `evals/` cases are optional and which ones apply to any repository. |
| `changes/README.md` | Lifecycle table steps 2, 6 and 8: who commits and pushes the approval and the closure, with a pointer to the host guide. |
| `README.md` | Quick start step 3: the owner approves, the agent commits and pushes. One sentence in Template releases about the eval secret. |
| `evals/README.md` | CI section: name the secret and point to the host guide. |
| `.agents/skills/sdlc-artifacts/SKILL.md` | Approval and Close: the agent commits and pushes the approval and closure the owner produced, so the owner stays able to review. |

Out of scope: any `scripts/`, `checks.json`, workflows, the ruleset itself, and the root baseline.

## Order of work

1. **Plan approval (owner).**
2. Edit the six files above.
3. **Verification.** `repo.py status --change docs-review-identity`, `repo.py verify --change docs-review-identity` (routes to `control-plane` through `changes/**`), `verify --full`.
4. **Candidate closure** with `repo.py close`, then the pull request with `Change-ID: docs-review-identity`. The agent commits and pushes the approval and the closure, so the owner is not the last pusher.

## Tests and proof

| Item | Proof |
|---|---|
| Nothing but documentation changed | `repo.py status` shows every changed path inside `write_scope`; the diff touches only `.md` files and this packet |
| No regression | `verify --full` passes |
| The adoption list is complete | every path added to `main` by #9 outside `changes/` and `scripts/tests/` appears in `docs/adoption.md` (checked by reading `git show --stat 449e4e2`) |

## Risks and mitigations

- **Documenting a degraded mode normalises it.** The text keeps the recommended mode first and calls the single-person mode degraded, as the existing guide does.
- **Claims about GitHub behaviour drift.** Only the two rules observed on 2026-10-05 are stated: a pull-request author cannot approve it, and `require_last_push_approval` excludes the last pusher.

## Rollback or recovery

Revert the squash commit.

## Open questions

None.
