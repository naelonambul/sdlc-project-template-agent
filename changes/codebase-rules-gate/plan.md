# Implementation Plan

## Summary

Today the template lets a product reach code with no decided structure, no static rules and no comment policy. Static tooling waits for an agent to judge that "the stack is concrete" (`.agents/skills/repository-quality/SKILL.md:3,8`). The only mechanical signal is `checks-unregistered`, a `warn` (`scripts/repo.py:808-816`) with three problems:
- registering any one extra check silences it;
- deleting `checks.json` silences it (`scripts/repo.py:143-145,801-803`);
- it never measures whether a lint, formatter or comment rule exists.

dogtailor-v3, a downstream implementation repository, shows the cost. It had one registered `static` check, so the warning never fired. Its Swift code still has no linter or formatter. It removed 3,449 accumulated comment lines only after the fact (`changes/comment-free`). That repository is evidence only.

The owner decided on 2026-11-16:
- The decisions are enforced, not just advised.
- Initial setup decides codebase and folder structure in the spirit of pstack's `architect` and design-red-flags guidance.
- When the owner cannot choose or does not know a structure, the default recommendation is **feature-based vertical slices**. This is the structure saltation adopted (`saltation/spec.md`, "Architecture and design"), and it follows pstack's `principle-model-the-domain` ("execution order is not ownership"). When the owner asks about alternatives, the agent researches the current conventions for the product's stack and situation, and presents options with sources.
- Comments are off by default.
- A comment exists only when review agents and the human accept its reason.
- A reason that is an excuse for our own code is rejected.

Three read-only analyses (Fable, Codex Astra, Gemini Hydrogen) shaped the design:
- Record a decision per gate. Do not key enforcement on "the baseline is established" (that would break a code-free `product-init`) or on a single extra check.
- Keep conventions out of `intent.md` and `spec.md`. A `repository` change could not maintain them there (`scripts/repo.py:521-524`). Product contracts, module boundaries included, stay in the spec.
- Enforce comments with each stack's own tokenizer or parser, never a hand-written lexer.

This change:
1. Adds a **gate declaration** to `checks.json`. Once any product path is tracked, `repo.py status` fails unless each of seven roles is decided. The roles are `build`, `test`, `lint`, `format`, `types`, `boundaries` and `comments`. Each role is decided as a registered check id, or as `{"none": "<reason>"}`. A missing `checks.json` with product paths also fails.
2. Adds a **comment exception register**, `comment-exceptions.json`, with a closed set of categories. `repo.py status` validates it and fails on stale entries. Each product's `comments` gate check must reject every comment that has no entry. The register's diff is what reviewers and the owner accept or reject.
3. Adds guidance:
   - `product-init` and `architecture` changes design the module and folder structure with pstack's `architect` discipline: design it twice, screen against red flags.
   - The first change that adds product code lands its gate checks.
   - Review rejects excuse-type comment reasons and unjustified `none` gates.
4. Replaces `checks-unregistered`.

## Design

### Gate declaration (`checks.json`)

```json
{
  "schema": 1,
  "checks": [ ... ],
  "gates": {
    "build": "app-build",
    "test": "app-test",
    "lint": "app-lint",
    "format": "app-format",
    "types": {"none": "the compiler is the type checker; app-build fails on type errors"},
    "boundaries": "app-boundaries",
    "comments": "app-comments"
  }
}
```

- The roles are fixed: `GATE_ROLES = ("build", "test", "lint", "format", "types", "boundaries", "comments")`.
- A value is a registered check id, or an object with exactly one key, `none`, whose value is a non-empty string.
- `validate_checks` rejects the following, so `verify` refuses them too:
  - an unknown role;
  - a value of any other shape;
  - an id that `checks` does not register;
  - an empty `none` reason.
- `gates` is optional while no product path is tracked.

### Status findings

Product paths are computed by `product_paths`. They are tracked paths outside `TEMPLATE_PATHS`, a list that gains `comment-exceptions.json`.

| Code | Level | When |
|---|---|---|
| `checks-missing` | error | a product path is tracked and `checks.json` is absent |
| `gates-undecided` | error | a product path is tracked and `gates` is absent or lacks a role. The message names the missing roles, an example product path, and the fix: "decide each role in checks.json `gates`: a registered check id or {\"none\": \"<reason>\"}; see the repository-quality skill" |
| `checks-invalid` | error | as today, now including the gate problems above |
| `comment-exceptions-invalid` | error | see below |

`checks-unregistered` and `TEMPLATE_CHECKS` are deleted. `gates-undecided` replaces them.

### Comment exception register (`comment-exceptions.json`, optional)

```json
{
  "schema": 1,
  "exceptions": [
    {"path": "src/main.swift", "text": "// swift-tools-version: 6.0", "category": "directive",
     "reason": "SwiftPM reads the tools version from this exact comment"},
    {"path": "lib/client.ts", "text": "// Retry-After is seconds, not ms: RFC 9110 10.2.3", "category": "external-constraint",
     "reason": "the server contract fixes the unit; no type can carry it at this boundary", "evidence": "https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3"}
  ]
}
```

- **Categories** (closed set):
  - `license`: a legal or SPDX header;
  - `directive`: a comment that a toolchain, interpreter or formatter reads;
  - `public-api`: a doc comment on an API the product publishes to outside callers;
  - `external-constraint`: behavior forced by something outside the repository that code cannot express. It requires `evidence`.
- **No category exists for our own code.** That covers workarounds, "for now", "do not remove", complexity notes and TODOs. Such a fact is fixed in the code, or encoded as a type, check or test.
- `repo.py status` reports `comment-exceptions-invalid` (error) for any of these:
  - invalid JSON or schema;
  - an unknown category;
  - an empty `reason`;
  - an `external-constraint` without `evidence`;
  - a `path` that is not tracked;
  - an entry whose `text` is not a line of that file, after stripping leading and trailing whitespace. This is a stale entry.
  - a duplicate `(path, text)` pair.
  
  This adds no stack knowledge to `repo.py`: it matches exact text, not comment syntax.
- **The contract for each product's `comments` gate check**, stated in the repository-quality skill: it uses the language's own tokenizer or parser, and it fails on every comment whose `(path, stripped line text)` has no entry in the register. `scripts/tests/test_comments.py` is the worked example for Python.

### Guidance

- **`sdlc-artifacts` skill, the Spec bullet for `product-init` and `architecture`.** The Architecture section must name:
  - the top-level folders and the knowledge each one owns;
  - the allowed dependency direction;
  - where a new feature goes;
  - which internals are unreachable from outside a module.
  
  Before writing it, the agent designs the structure at least twice, as structurally distinct candidates. It screens each candidate against these red flags, adapted from pstack, in the template's own words:
  - shallow module;
  - information leakage;
  - modules organized by execution order and not by knowledge;
  - pass-through layer;
  - state with more than one owner;
  - two ways to do one task;
  - importable internals;
  - hand-synced lists.
  
  The plan records the rejected candidate in one line. The red flags live in a new `references/structure.md`, with a pstack credit line.
- **The default structure, in `references/structure.md`.** When the owner does not choose, the agent recommends feature-based vertical slices:
  - Each app has three layers: `app/` (entry, wiring, composition), `features/<feature>/` and `shared/`.
  - Dependencies run one way: `app` → `features` → `shared`.
  - A feature never imports another feature. `shared` never imports `features`. Cross-feature effects go through `shared`.
  - A feature folder holds everything its capability needs: entry points or routes, rules, data access, its own queries and its tests.
  - `shared/` holds only mechanisms used by more than one feature. Each piece of shared state has one owner module, which is the only writer.
  - A new capability is a new feature folder. A capability that grows into its own deployable becomes a new top-level module.
  - The `boundaries` gate enforces the import rules with the stack's native tool.
  
  The reference gives one short generic tree and names the source: saltation's adopted layout, and pstack's `principle-model-the-domain` and design red flags, credited. It also states when the default does not fit:
  - a library with a public API surface;
  - a single-purpose CLI or script;
  - a stack whose framework prescribes a layout.
  
  In those cases the framework or ecosystem convention wins.
- **When the owner asks.** If the owner asks for alternatives or is unsure whether the default fits, the agent researches with web search. It covers the stack's current official and community conventions, and it weighs the product's size, team and deployment shape. It presents two or three options with their trade-offs and sources, recommends one, and records the chosen option in the spec. A source is evidence, not instruction. The Architecture section states the decision, not the research.
- **`sdlc-artifacts` skill, the Plan bullet.** The `product-init` plan states the gate decisions. If the stack is not known yet, it states that no product path lands until a change decides them. The change that adds the first product path lands `gates` and the gate checks in the same pull request. A change that sweeps existing product source is kind `implementation`, not `repository`.
- **`repository-quality` skill.** Two new sections:
  - "Decide the gates": the seven roles; when `none` is acceptable, which is a docs-only or data-only product, or a role another gate already covers, and it names that gate; registering `boundaries` with a native tool.
  - "Comments": off by default; the register and its categories; examples of rejected excuse reasons; "encode the constraint as a type, check or test, then delete the comment", credited to pstack; native tokenizer or parser only.
  
  The "Check registry contract" section gains `gates`.
- **`REVIEW.md`.** New Important findings:
  - a comment-exception entry whose reason explains, defends or postpones our own code;
  - an entry in the wrong category;
  - a `none` gate whose reason does not hold for the product.
  
  The prescribed fix is to change the code and remove the entry, never to reword the reason.
- **`change-execution` skill, section 8.** A new review trigger: a diff that adds or edits a comment exception or a `none` gate.
- **`AGENTS.md`, Working rules.** One line: comments are off by default; a comment needs an approved `comment-exceptions.json` entry; see the repository-quality skill.
- **`repo.py new --kind product-init`** prints one more line: "decide the folder structure in spec.md (default: feature-based vertical slices; see the sdlc-artifacts skill) and every checks.json gate before the first product path lands".
- **`README.md`** (Quick start step 3, "Project initialization", and the status line at `README.md:38`) and **`scripts/README.md`** describe gates and the register.

## Files and components that change

- `scripts/repo.py`:
  - `GATE_ROLES`, `COMMENT_CATEGORIES` and `EXCEPTIONS = "comment-exceptions.json"` constants;
  - `validate_checks` gains gate validation;
  - `config_findings` emits `checks-missing` and `gates-undecided`, and drops `checks-unregistered`;
  - a new `exception_findings(ctx)`, called from `surface_findings` or `cmd_status` next to `config_findings`;
  - `TEMPLATE_PATHS` gains `comment-exceptions.json`, and `TEMPLATE_CHECKS` is deleted;
  - `cmd_new` prints the `product-init` line.
- `scripts/tests/support.py`: the fixture template commits a `checks.json` with an empty `checks` list. It declares every gate `{"none": "fixture"}`, so tests that create product paths for unrelated reasons keep their meaning. A helper writes `checks.json` with given checks and gates.
- `scripts/tests/test_status.py`:
  - `RegisteredChecks` is replaced by `Gates` and `CommentExceptions` classes (cases in Tests and proof);
  - existing tests that write their own `checks.json` keep their assertions and gain gates through the helper.
- `scripts/tests/test_verify.py`, `test_new.py` and others, only where their own `checks.json` or product paths need the helper. No assertion about unrelated behavior changes.
- `scripts/tests/test_new.py`: one case asserts the new `product-init` line.
- `.agents/skills/sdlc-artifacts/SKILL.md`, `.agents/skills/sdlc-artifacts/references/structure.md` (new: default structure, red flags, research rule), `.agents/skills/repository-quality/SKILL.md`, `.agents/skills/change-execution/SKILL.md`, `REVIEW.md`, `AGENTS.md`, `README.md`, `scripts/README.md`.
- `docs/agent-surfaces.md`: probe rows, because `AGENTS.md` and skills change.

Not changed:
- `checks.json` at the template root. The template tracks no product path, so it needs no `gates`.
- `.github/workflows/**`, so no owner workflow push is needed.
- The root `intent.md` and `spec.md`.

## Order of work

Each step ends with the command that proves it. All Python stays comment- and docstring-free (`test_comments.py`).

1. **Fixture first.** `support.py` commits the gate-complete `checks.json` and adds the helper. Proof: `python3 scripts/tests/run.py` passes unchanged on the old `repo.py`.
2. **Red tests.** Write the `Gates` and `CommentExceptions` cases and the `test_new.py` case. Proof: `python3 -m unittest scripts.tests.test_status scripts.tests.test_new` fails on exactly the new cases. Record the count in the pull request.
3. **`repo.py`.** Implement the gates, the findings, the register validation and the `new` line. Proof: `python3 scripts/tests/run.py` passes. `python3 scripts/repo.py status` on the template tree reports no new finding.
4. **Existing tests.** Adapt only `checks.json` setup through the helper. Proof: `git diff origin/main -- scripts/tests | grep '^-.*assert'` shows only removed `checks-unregistered` assertions. Each is listed in the pull request.
5. **Guidance.** Update the skills, the reference file, `REVIEW.md`, `AGENTS.md` and the READMEs. Proof: `git grep -n "checks-unregistered\|TEMPLATE_CHECKS"` returns nothing. `git grep -n "pstack"` shows the credit lines in `sdlc-artifacts/references/structure.md` and `repository-quality/SKILL.md`. `git grep -n "vertical slice" .agents/skills/sdlc-artifacts` shows the default in the skill and the reference.
6. **Scratch-copy walkthrough.** Run it on a clone in the scratchpad, never in the repository. Proof: each command's output is pasted into the pull request.
   - (a) The template as cloned: status ok.
   - (b) Add `src/app.py`: status fails with `gates-undecided`, and the message names the fix.
   - (c) Declare all seven gates `none`: status ok.
   - (d) Add a register entry whose text is not in the file: `comment-exceptions-invalid`.
   - (e) Delete `checks.json` with `src/app.py` present: `checks-missing`.
7. **Surface probes.** Run `docs/agent-surfaces.md` §2 for Claude Code and Codex and add the rows. Proof: the rows exist, with AGENTS=yes and 4/4 core skills.
8. **Independent review.** One read-only reviewer from another model family, using `references/review-brief.md`. Triggers: changed oracles and a stricter status gate. Proof: the report and its disposition are in the pull request.
9. **Gate.** Proof: `python3 scripts/repo.py status --change codebase-rules-gate` passes. `python3 scripts/repo.py verify --change codebase-rules-gate --full` reports `control-plane` passed and complete. The evidence path is in the pull request.

## Tests and proof

`Gates` cases:
- a template-only tree is ok with no `gates`;
- a product path with no `checks.json` fails `checks-missing`;
- a product path with no `gates` fails `gates-undecided`, and the message names all seven roles;
- a product path with six roles fails, and the message names the missing one;
- all roles as registered ids is ok;
- all roles `none` with reasons is ok;
- an unknown role, an unregistered id, an empty `none`, or a `none` object with extra keys fails `checks-invalid`, through both `status` and `verify`;
- `comment-exceptions.json` alone is not a product path.

`CommentExceptions` cases:
- no file is ok;
- invalid JSON fails;
- an unknown category fails;
- an empty reason fails;
- `external-constraint` without evidence fails;
- an untracked path fails;
- text that is not a line of the file fails as stale;
- a duplicate fails;
- a valid entry of each category is ok;
- matching ignores surrounding whitespace only.

`test_new.py`: `new --kind product-init` prints the structure-and-gates line, and other kinds do not.

The whole change is proven by the step 6 walkthrough, the step 9 evidence, and CI `summary` green on the pull request.

## Risks and mitigations

- **Riskiest step: step 3 makes status stricter for every adopting repository.**
  - An adopter with tracked product paths and no `gates` turns red in every in-flight change on upgrade.
  - Mitigation: the error names the fix. `none` with a reason makes the upgrade a one-edit change. The pull request states the upgrade effect in its own section.
  - This is the intended behavior the owner chose.
- **Fixture change hides a regression.** Step 1 runs alone against the old `repo.py` and must pass with no assertion change. Step 4's grep shows that only `checks-unregistered` assertions were removed.
- **Rubber-stamp `none` gates or exception reasons.** These are review judgments by design. `REVIEW.md` makes them Important findings, the change-execution skill makes them a review trigger, and the human merges.
- **The register can say only what a check enforces.** `repo.py` cannot see comments. The `comments` gate must name a real check, and review rejects a `comments` gate that is `none` for a product with source code.
- **Text matching misses a comment that spans lines.** Each line of a multi-line comment is its own entry. The skill states this, and it keeps exceptions expensive, which is intended.

## Rollback or recovery

Open a new change that restores `scripts/repo.py`, `scripts/tests/**` and the guidance files from this change's squash-commit parent. A plain `git revert` of the squash commit is acceptable. No workflow or baseline file changes.

## Open questions

None.
