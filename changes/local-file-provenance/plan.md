# Implementation Plan

## Summary

Issue #37: an agent mistook an untracked `uv.lock`, likely managed by the owner's IDE, for an artifact of its own task. It deleted and regenerated the file, and the result could not be confirmed identical to the original. Nothing in the shared guidance covers this.

This change adds an evidence-first procedure for pre-existing local files. It is a `repository` change: guidance text only. It changes no `scripts/**`, `checks.json`, `.github/**`, or lifecycle semantics.

### Decisions

- **The rule goes in `AGENTS.md`, the procedure in `sdlc-artifacts`.** The rule applies in nearly every session, and the detail is conditional, which is how `AGENTS.md` asks to split them.
- **No new skill.** `sdlc-artifacts` already owns implementation and write-scope judgment. A new skill would add one more adapter and discovery surface for six steps of text.
- **No guard or `repo.py` enforcement.** The issue's acceptance criteria ask for guidance. The guard cannot tell a pre-existing file from one the session created, and an `rm` rule would mostly interrupt cleanup of the agent's own files.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `AGENTS.md`: one rule under "Working rules".
- `.agents/skills/sdlc-artifacts/SKILL.md`: a new "Pre-existing local files" subsection after "Implement".
- `docs/agent-surfaces.md`: smoke-test result rows.

### Text for `AGENTS.md`

Add under "Working rules", after the rule on deleting unrelated changes:

```markdown
- Do not delete, overwrite, regenerate, move, or change ignore rules for a file that existed before the current task until you have established its origin; follow "Pre-existing local files" in the `sdlc-artifacts` skill. An out-of-scope path is a status finding, not permission to remove or hide it.
```

### Text for `sdlc-artifacts`

Add after the "Implement" list, before "## Close":

```markdown
### Pre-existing local files

A file the current task did not create may belong to the owner's IDE or tools, whether it is tracked, untracked or ignored. Before deleting, overwriting, regenerating, moving it, or changing an ignore rule that affects it:

1. Establish its Git state with `git status --short --ignored -- <path>`.
2. Identify the ignore rules that apply: root and nested `.gitignore` files, `.git/info/exclude`, the global `core.excludesFile`, and relevant IDE or tool ignore settings. Use `git check-ignore -v -- <path>` where it applies, and report the rule's source.
3. Assess its origin from the file's birth and modification times, its contents, the relevant project and tool configuration, and narrowly relevant IDE or tool logs. A timestamp alone proves nothing. Do not read or expose unrelated sensitive log data.
4. Report the evidence, your confidence and what remains uncertain, the impact on the current scope and status, and a recommended next action.
5. While its origin is uncertain, leave the file unchanged and wait for the owner's decision before any change that could lose it.

An out-of-scope path is reported as out of scope. Never delete it, regenerate it, or alter ignore rules to make `status` pass. Files this session demonstrably created are not covered.
```

## Order of work

Each step is one coordinator edit, so the route is single agent.

1. Edit `AGENTS.md`. Proof: `grep -c 'existed before the current task' AGENTS.md` prints `1`.
2. Edit `.agents/skills/sdlc-artifacts/SKILL.md`. Proof: `grep -c '### Pre-existing local files' .agents/skills/sdlc-artifacts/SKILL.md` prints `1`.
3. Run the smoke-test procedure in `docs/agent-surfaces.md` and add the result rows. Proof: 4/4 core skills in each new row.
4. Commit, run `python3 scripts/repo.py verify --change local-file-provenance --full`, then close per `changes/README.md`.

## Tests and proof

- `python3 scripts/repo.py status --change local-file-provenance` passes, which shows every changed path is inside `write_scope`.
- `python3 scripts/repo.py verify --change local-file-provenance --full` reports no `failed`, `blocked`, or `not-run` check.
- The smoke test confirms `AGENTS.md` and skill discovery, because this change touches both.
- Each acceptance criterion of #37 maps to text above: the procedure covers tracked, untracked and ignored files; step 2 covers every ignore layer; steps 4 and 5 put the report before a destructive change; the closing paragraph covers out-of-scope paths.
- This is advisory text, so no check proves agents follow it.

## Risks and mitigations

- **Workers may not read `AGENTS.md`.** Some subagents omit project instructions, and briefs do not carry this rule. They are still limited to `write_scope`, and the delegating agent reviews their diff. A file inside `write_scope` is the remaining gap, so a later change can add the rule to the brief if it recurs.
- **Friction on routine cleanup.** The closing sentence excludes files this session demonstrably created.
- **`git status --ignored` with a path** behaves differently across Git versions only in formatting, and step 1 reads the state by eye.

## Rollback or recovery

Before merge, drop the branch. After merge, open a new change that removes the two text blocks.

## Open questions

None.
