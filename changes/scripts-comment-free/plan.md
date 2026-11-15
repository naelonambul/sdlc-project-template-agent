# Implementation Plan

## Summary

The template's own Python under `scripts/**` carries no comments and no docstrings. A new control-plane test enforces this. The only allowed comment is a line-1 `#!/usr/bin/env python3` shebang on a file whose Git mode is `100755`.

The owner chose the strict form on 2026-11-16. The reasoning: the template's code is the example that agents copy. A downstream repository built with this template's process (dogtailor-v3, `changes/comment-free`) accumulated 3,449 comment lines of agent residue, such as packet ids, review notes, SHAs, stale plan citations and section banners. Then it needed its own checker to remove them. That repository is evidence only. Its sha256 pins on copied template files are its own upgrade concern, not a constraint on this change.

Three read-only analyses (Fable, Codex Astra, Gemini Hydrogen) informed the design:
- Put the check inside the existing `control-plane` suite. A new `checks.json` entry is not needed. That avoids `TEMPLATE_CHECKS` in `scripts/repo.py:687`, the `checks-unregistered` warning, and a workflow handoff.
- Use only `tokenize` and `ast`, and check only Python. Hand-written lexers for other languages have proven costly and produce false positives.
- Convert the docstrings that `argparse` reads before deleting them.
- Do not port pstack's Comment Sicko agent.

Inventory at base `51ca588`, measured with `tokenize` and `ast`:
- 80 comment tokens in 9 files:
  - 3 shebangs;
  - 4 `# noqa: E402`;
  - about 40 section-banner lines (29 divider lines plus their section titles);
  - the rest are rationale lines, listed below with their coverage.
- 48 docstrings in 13 files. All string-expression statements are docstrings.
- Shebangs: `scripts/hooks/guard.py` is `100755`. `scripts/repo.py` and `scripts/tests/run.py` are `100644`, and every caller invokes them as `python3 <path>`.

Out of scope, unchanged:
- `.github/workflows/repository.yml` comments, including the `# vX.Y.Z` annotations that make SHA-pinned actions readable. A change there needs an owner workflow push, and the check would need a YAML lexer.
- `.gitignore` and `.gitattributes`.
- Markdown. The `<!-- sdlc:baseline-unestablished -->` marker is load-bearing.
- Guidance for adopting repositories, which is a separate change.

## Files and components that change

- `scripts/tests/test_comments.py` (new). It is standard library only. A pure function `findings(path, text, executable) -> list[str]` reports:
  - every `tokenize.COMMENT` token, except line 1 when it equals `#!/usr/bin/env python3` and `executable` is true;
  - every `ast.Expr` whose value is a `str` constant, which covers module, class and function docstrings and bare strings.
  
  Each finding is `<path>:<line>: <what>; <what to do instead>`. The instead text is: "delete it; put a durable fact in a test, a name, an assertion message, or scripts/README.md". A file that does not tokenize or parse is itself a finding.
  
  Test cases:
  - Every Python file under `scripts/` from `git ls-files -s -- 'scripts/*.py'` (mode taken from that output) has no findings.
  - Fixtures, each run through `findings`:
    - a `#` comment is found;
    - a module, class and function docstring are each found;
    - a shebang on a non-executable file is found;
    - a shebang on line 2 is found;
    - a different interpreter shebang is found;
    - a valid shebang on an executable file is not found;
    - `#` inside a string, an f-string and a regex literal is not found;
    - a string used as a value (assignment, call argument, `description=`) is not found;
    - a syntax error is found.
  - The real-tree case asserts at least 10 files were scanned, so an empty `ls-files` result cannot pass.
- `scripts/repo.py`:
  - delete the line-1 shebang, all comments and all docstrings;
  - `main` passes the literal first line of the old docstring, ``"Repository control plane: `status`, `verify`, `new` and `approve`."``, as `description=` instead of `__doc__.splitlines()[0]`, so help output is unchanged.
- `scripts/tests/run.py`:
  - delete the shebang and docstrings;
  - `description=` becomes the literal first line of the old docstring.
- `scripts/hooks/guard.py`:
  - keep the shebang and mode `100755`;
  - delete comments and docstrings;
  - `description=` becomes a module constant `USAGE`, holding the old module docstring text exactly, and `RawDescriptionHelpFormatter` stays. Help output is unchanged.
- `scripts/tests/__init__.py`, `support.py`, `test_approve_close.py`, `test_guard.py`, `test_new.py`, `test_run.py`, `test_status.py`, `test_support.py`, `test_verify.py`, `test_workflow.py`: delete comments and docstrings. Delete the four `# noqa: E402`; they mark imports inside functions, and no linter runs here. A test or class name that loses the meaning its docstring carried is renamed to carry it.
- `scripts/README.md`:
  - one sentence: owned Python here carries no comments or docstrings, `scripts/tests/test_comments.py` enforces it, and a fact goes into a test, a name, an assertion message or this README;
  - add any fact from a deleted module docstring that the README does not already state. Known gap: `repo.py`'s pointer to `changes/README.md` for the change model.
- `docs/agent-surfaces.md`: one results row for the smoke probes. This change touches the guard, and `docs/agent-surfaces.md` §2 requires a re-run.

`checks.json`, `scripts/repo.py`'s `TEMPLATE_CHECKS` and `.github/workflows/**` do not change.

## Rationale comments and where their fact lives

Each is deleted. The fact is covered as listed, or the implementer adds the named coverage before deleting.

| Comment | Fact | Coverage |
|---|---|---|
| `scripts/repo.py:43-44` | `repository` kind inherits no baseline, may not modify an established one | `test_status.py` `test_repository_change_cannot_edit_established_baseline`; `changes/README.md` Kinds |
| `scripts/repo.py:363-364` | merged packet edited later needs scope | `test_status.py` `test_editing_a_merged_packet_outside_scope_fails` / `_inside_scope_passes` |
| `scripts/repo.py:564-567` | the base decides establishment; adding the marker cannot exempt a change | `test_status.py` `test_the_marker_cannot_unestablish_an_established_baseline` |
| `scripts/repo.py:681` | template-owned paths vs product material | the constant's name; add a rename only if unclear |
| `scripts/repo.py:885` | a group run directly in CI is wired | `test_status.py` `CheckWiring` cases |
| `scripts/repo.py:945-947` | complete only when nothing unrun, group runs partial, changed files void the run | `test_verify.py` lines 96-97 and `test_files_changed_during_the_run_leave_it_incomplete` |
| `scripts/repo.py:1029` | other packets fail the gate only on invalid records | the implementer confirms a `test_status.py` case exists or adds one |
| `scripts/hooks/guard.py:364` | change.json without proposed content is denied | `test_guard.py` `test_edit_of_change_json_denied_without_proposed_content` |
| `scripts/hooks/guard.py:399` | the guard never crashes the agent loop | `test_guard.py` `test_malformed_tool_input_allowed_with_note` |
| `scripts/tests/support.py:25-26` | fixture commits must not start auto maintenance | `test_support.py` `NoAutoMaintenance` |
| `scripts/tests/__init__.py:6` | inherited Git env vars are cleared | rename or keep the loop's variable name self-explanatory |
| `scripts/tests/test_workflow.py:69` | job-level `if:` turns not-applicable into a skip | move into the assertion message |

## Order of work

Each step ends with the command that proves it.

1. **Red check.** Add `scripts/tests/test_comments.py`. Proof: `python3 -m unittest scripts.tests.test_comments` passes all fixture cases and fails the real-tree case, listing findings in `repo.py`, `guard.py` and the tests. Record the finding count in the Verification section.
2. **Help snapshot.** Before editing, save `python3 <script> --help` stdout and stderr for `scripts/repo.py`, `scripts/hooks/guard.py` and `scripts/tests/run.py`, plus `python3 scripts/repo.py status --help`, to files outside the repository. Proof: the files exist.
3. **Runtime docstrings.** Convert the three `description=` uses as specified. Then delete the module docstrings and shebangs in `repo.py` and `run.py`. Proof: each `--help` output diffs empty against step 2.
4. **Clean `scripts/repo.py` and `scripts/hooks/guard.py`.** Use the coverage table. Proof: `python3 scripts/tests/run.py` passes except the real-tree case, which no longer lists these two files.
5. **Clean `scripts/tests/**`.** Proof: `python3 scripts/tests/run.py` passes, including `test_comments`.
6. **README.** Proof: `git grep -n "test_comments" -- scripts/README.md` returns one line.
7. **Equivalence.** For every changed `.py` file, compare the token stream of base and head with `COMMENT`, `NL`, docstring statements and `ENCODING` removed. The only differences allowed are the `description=` conversions, the `USAGE` constant, and any renames, each listed in Verification. Proof: a throwaway script in the scratchpad, not committed; its output is pasted into Verification.
8. **Surface probe.** Run `docs/agent-surfaces.md` §2 for Claude Code and Codex and add the row. Proof: the row exists. AGENTS=yes and every core skill is listed for both agents.
9. **Gate.** Proof: `python3 scripts/repo.py status --change scripts-comment-free` passes and `python3 scripts/repo.py verify --change scripts-comment-free --full` reports `control-plane` passed and complete. Record the evidence path in Verification.

## Tests and proof

- `test_comments.py` proves the rule both ways through its fixtures. The real-tree case was red at step 1 and green at step 5.
- Help output for the three entry points is byte-identical to the base.
- The token-stream equivalence shows that no code changed besides the listed conversions.
- Whole change: `repo.py verify --change scripts-comment-free --full` complete and passed, and CI `summary` green on the pull request.

## Risks and mitigations

- **Losing a fact that only a comment held.** The coverage table maps each rationale comment to a test or name before deletion. The equivalence step catches accidental code edits.
- **A docstring that runtime reads.** Only the three `argparse` uses read `__doc__` (`git grep -n "__doc__" scripts` at base). Step 3 converts them first, and `test_support.py` asserts `usage: repo.py` and `usage: guard.py`. After the change, `git grep -n "__doc__" scripts` must return nothing.
- **`unittest -v` loses docstring descriptions.** Verbose output then shows test names only. Accepted; names carry the meaning.
- **Shebang removal on `repo.py` and `run.py`.** Both are `100644` and every documented call is `python3 <path>`. Before removing, `git grep -n -E "scripts/(repo|tests/run)\.py" -- ':!changes' | grep -v -E "python3? +[^ ]*scripts/(repo|tests/run)\.py"` is run, and every remaining hit is read by hand to confirm it is not a direct execution.
- **Riskiest step: step 4 on `guard.py`.** It is the in-session guard, and a broken guard denies or allows wrongly. Mitigation: `test_guard.py` runs unchanged against the edited file, and step 8's probe exercises it in Claude Code.

## Rollback or recovery

A new change that restores `scripts/**` from this change's squash-commit parent and drops `test_comments.py`. A plain `git revert` of the squash commit is acceptable. No workflow, `checks.json` or baseline file changes, so no owner push is involved.

## Verification

Filled in during implementation: the step 1 finding count, the step 3 help diff, the step 7 equivalence output, the step 8 probe row, and the step 9 evidence path.

## Open questions

None.
