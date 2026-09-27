# Implementation Plan

## Summary

`REVIEW.md` still says "accepted artifacts" in two places, a leftover from the v1 process. v1 gated work on a front-matter `status: accepted`. This template gates it on digest-bound approval claims in `change.json` (`AGENTS.md`, SDLC gates). The `template-vnext-control-plane` change already rewrote `REVIEW.md` lines 3 and 10 to "approved" but missed lines 22 and 32. A reviewer reading "accepted artifacts" may look for an acceptance status the template does not have. `docs/adoption.md` asks adopters to remove exactly this kind of leftover rule.

This docs-only `repository` change replaces "accepted" with "approved" in those two lines. It changes no behaviour, no review pass, and no finding level.

The finding came from a prompt audit of the repository's agent instruction files, run on 2026-09-27.

## Files and components that change

`write_scope`: `["REVIEW.md"]`

| Path | Line | Before | After |
|---|---|---|---|
| `REVIEW.md` | 22 | `violate accepted artifacts or repository policy` | `violate approved artifacts or repository policy` |
| `REVIEW.md` | 32 | `why it conflicts with the accepted artifacts or repository behavior;` | `why it conflicts with the approved artifacts or repository behavior;` |

No other line of `REVIEW.md` changes.

Out of scope, and left unchanged:

- "Merge accepted change-local `intent.md`/`spec.md`" in `changes/README.md` and `.agents/skills/sdlc-artifacts/SKILL.md`. There, "accepted" describes the packet's copies at close. The wording is consistent across both files and does not refer to a status.
- `docs/adoption.md`, which uses "accepted" when describing an adopter's earlier process.
- Every other instruction file. The audit found nothing else above low confidence.

## Order of work

1. Edit the two lines of `REVIEW.md` exactly as in the table above.
   Proof: `git diff --stat -- REVIEW.md` shows 2 insertions and 2 deletions. `grep -n -w accepted REVIEW.md` prints nothing.
2. Run `python3 scripts/repo.py status --change review-approved-wording` and `python3 scripts/repo.py verify --change review-approved-wording --full`.
3. Add the candidate `closure.json` citing the local verify evidence. Commit as `mini26-agent`, push `change/review-approved-wording`, and open one PR with `Change-ID: review-approved-wording`.

## Tests and proof

- `grep -n -w accepted REVIEW.md` returns no match (exit 1).
- `git diff main -- REVIEW.md` shows only the two planned line changes.
- `repo.py status --change review-approved-wording` reports no error. Before closure it reports `readiness=ready`; after closure, `closure=candidate`.
- `repo.py verify --change review-approved-wording --full` reports the `control-plane` check passed, with no `failed`, `blocked` or `not-run` check. `REVIEW.md` is not routed to any check, so `--full` is what runs the suite.
- CI `summary` passes on the head that contains `closure.json`.

## Risks and mitigations

- **Meaning shift.** "Approved" is the word `AGENTS.md`, `REVIEW.md` lines 3 and 10, and `changes/README.md` already use for the same artifacts. The finding levels and review passes do not change.
- **Hidden string dependency.** `git grep -n 'accepted artifacts'` across the repository shows only these two `REVIEW.md` lines. No test or script matches on the text.

## Rollback or recovery

Revert the squash commit. The change touches only prose in `REVIEW.md` and its own packet.

## Open questions

None.
