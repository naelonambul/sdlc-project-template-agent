# Implementation Plan

## Summary

`scripts/repo.py new` takes `--scope` as a repeatable option (`action="append"`),
so each pattern needs its own `--scope`. `AGENTS.md:39` and `changes/README.md:17`
already write it as `[--scope <pattern>]...`. The `sdlc-artifacts` skill writes
`--scope <pattern>...`, which reads as one `--scope` followed by several patterns.
The parser rejects `--scope a b`.

This docs-only `repository` change aligns the skill with the other two places.
It changes no behaviour.

The finding came from a prompt audit of `dogtailor-v3`, which carries a byte-identical copy of this
skill. Dogtailor is making the same correction in its own change,
`instruction-truth-fixes`. Correcting the template too keeps the copies from
diverging again at the next template upgrade.

## Files and components that change

`write_scope`: `[".agents/skills/sdlc-artifacts/SKILL.md"]`

Line 13 only. In the command example, replace the fragment

```text
--title "<summary>" --scope <pattern>...`
```

with

```text
--title "<summary>" [--scope <pattern>]...`
```

The rest of the line and the rest of the file stay unchanged.

Out of scope: `AGENTS.md`, `changes/README.md` and `docs/adoption.md`. The first
two already use the correct form, and `docs/adoption.md` writes out every
`--scope` explicitly.

## Order of work

1. Edit the fragment on `.agents/skills/sdlc-artifacts/SKILL.md` line 13 as above.
   Proof: `git diff --stat main` shows one line changed in that file, plus this packet.
2. Run `python3 scripts/repo.py status --change scope-flag-syntax` and
   `python3 scripts/repo.py verify --change scope-flag-syntax --full`.
3. Add the candidate `closure.json` citing the local verify evidence. Commit as
   `mini26-agent`, push `change/scope-flag-syntax`, and open one pull request with
   `Change-ID: scope-flag-syntax`.

## Tests and proof

- These checks confirm the new form:
  - `grep -rn -- "--scope <pattern>\.\.\." AGENTS.md changes/README.md .agents docs`
    prints nothing.
  - `grep -rn -- "\[--scope <pattern>\]\.\.\." AGENTS.md changes/README.md .agents`
    prints the three lines.
- `repo.py status --change scope-flag-syntax` reports no error: `readiness=ready`
  before closure and `closure=candidate` after it.
- `repo.py verify --change scope-flag-syntax --full` reports `control-plane`
  passed, with no `failed`, `blocked` or `not-run` check.
- CI `summary` passes on the head that contains `closure.json`.

## Risks and mitigations

- **Behaviour.** None: the parser and its tests are untouched. The new text matches
  what `repo.py new --help` accepts.
- **Downstream copies.** Projects that adopted the template pick this up at their
  next upgrade. Dogtailor applies it now in `instruction-truth-fixes`.

## Rollback or recovery

Revert the squash commit.

## Open questions

None.
