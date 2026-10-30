# Implementation Plan

## Summary

The steps for closing a change and the guard's rules are written out in more than one place, so a rule change has to find every copy. The last few changes each had to decide which copies to touch. The overlap is modest, so this change is small: it keeps `changes/README.md` as the source for the lifecycle and `scripts/hooks/README.md` as the source for the guard, and replaces the other copies with links. No rule changes.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `.agents/skills/sdlc-artifacts/SKILL.md`, section Close: the five numbered steps become a pointer to the Lifecycle and Closure sections of `changes/README.md`, plus the only items that are guidance for an agent rather than the model:
  - run the probes in `docs/agent-surfaces.md` when the change touches `AGENTS.md`, a skill or the guard;
  - `git add` the new `closure.json`, because `commit -a` does not pick it up;
  - make the last push yourself, because the owner can approve only a pull request the agent identity authored and pushed last.
- `README.md`:
  - Quick start step 7 points to Lifecycle in `changes/README.md` instead of listing its steps.
  - The `scripts/hooks/guard.py` bullet and Enforcement layer 2 each give one sentence and link to `scripts/hooks/README.md`.
  - Agent neutrality drops its list of skill names, which `.agents/skills/` already defines.
- `docs/agent-surfaces.md`: the probe row, required because a skill changes.

`AGENTS.md` and `changes/README.md` do not change.

## Order of work

1. Edit `.agents/skills/sdlc-artifacts/SKILL.md`. Proof: `grep -n "changes/README.md" .agents/skills/sdlc-artifacts/SKILL.md` still shows the Close pointer, and the three items above are present.
2. Edit `README.md`. Proof: `grep -c "scripts/hooks/README.md" README.md` is 2.
3. Run the smoke probe and add the row to `docs/agent-surfaces.md`. Proof: the row exists, and the probe lists all four skills.
4. `python3 scripts/repo.py status --change docs-dedupe` and `python3 scripts/repo.py verify --change docs-dedupe --full` pass, then close per `changes/README.md`.

## Tests and proof

- Every removed sentence is checked against its target, so no rule exists only in the removed text. The pull request lists any that had to move.
- `git diff --stat` shows only the three files plus this packet, with more lines removed than added.
- The control-plane tests pass.

## Risks and rollback

- **Riskiest step: an agent reading only the skill misses a closing rule.** The skill loads when closing, and `changes/README.md` is then one more read of about 2,500 tokens. In exchange, the skill body gets shorter and cannot drift. `repo.py close` and CI enforce the rules regardless of what was read.
- Rollback: revert the squash commit.

## Out of scope

- `AGENTS.md`, `REVIEW.md`, `changes/README.md`, `docs/host-setup.md`, `scripts/hooks/README.md`.
- Any change to rules or behavior.
