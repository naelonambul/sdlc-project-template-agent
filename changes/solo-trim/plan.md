# Implementation Plan

## Summary

The repository is operated by agents and managed by one person. The agent works under its own GitHub App identity (`mini26-agent[bot]` opened pull requests #1 to #8); the owner approves artifacts with `repo.py approve`, reviews each pull request, and merges it. The template still carries material written for other setups and for other repositories adopting it: a brownfield adoption guide, a three-way review-mode comparison and a trust-mode record, a "who pushes what" matrix, per-tool skills for analysis tools nobody here uses, and a model-driven eval runner with its own test suite. None of it changes what `repo.py`, CI or the guard enforce. This change removes it and rewrites the remaining documents for the one real setup.

What stays is the control plane the owner actually uses: `repo.py` and its tests, `checks.json`, the `repository` workflow, the guard hook, the four process skills (`sdlc-artifacts`, `change-execution`, `verification-map`, `repository-quality`), `REVIEW.md`, `docs/agent-surfaces.md`, and the frozen change history.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

Deleted:

- `docs/adoption.md`: adoption of the template by an existing repository. This repository is the only one.
- `.agents/skills/context7/`, `.agents/skills/serena/`, `.agents/skills/graphify/` and their `.claude/skills/` symlinks: per-tool usage policies for tools the owner does not run here. A tool's own interface documents its use.
- `scripts/evals.py`, `evals/` (five cases and README), `scripts/tests/test_evals.py`: the model-driven eval runner. It was kept as a local tool in `remove-evals-workflow`; for a single operator who does not change `AGENTS.md` or the guard often, a 700-line runner plus tests is more to maintain than it proves. The guard keeps its unit tests; agent-surface drift is checked by the manual probes in `docs/agent-surfaces.md`.

Rewritten:

- `docs/host-setup.md`: one setup, the one in use. Squash-only merges; the agent's GitHub App identity with its permission limits, kept as a short checklist; the ruleset with one required approval and last-push approval, which works because the bot, not the owner, authors and last-pushes each pull request; the read-only host check; and one paragraph each on running without a ruleset and on a session that pushes under the owner's own token (it cannot be approved by the owner, so merge it unreviewed or let the bot push last). The review-modes table, the "Who pushes what" matrix and the trust-mode record go; what survives of them is one rule: the bot makes the last push.
- `REVIEW.md`, Separation of duties: the agent's self-review is never the human gate; the owner's `repo.py approve` claims and the owner's merge are. No sentence about pull-request authorship or last pushers.

Edited:

- `README.md`: quick-start step 3 loses the push-eligibility sentence; the control-plane list drops the evals bullet and the three tool skills; the "Template releases" section and the adoption sentence in "Project initialization" go; the agent-neutrality section lists the four remaining skills.
- `AGENTS.md`: drop the `evals.py` command, the Context7/Serena/Graphify working rule and the sentence about their `.gitignore` entries.
- `changes/README.md`: drop the adoption sentence in Kinds; lifecycle steps 2 and 8 say the owner approves and the agent commits, pushes and opens the pull request, with no ruleset conditions.
- `.agents/skills/sdlc-artifacts/SKILL.md`: drop the adoption pointer, the "Who pushes what" pointer and the eval step in Close; keep one clause that the agent makes the last push, with the reason.
- `docs/agent-surfaces.md`: the three sentences that cite evals describe the same probes as manual `claude -p` runs; the 2026-10-05 smoke row keeps its observation.
- `scripts/README.md`: drop the `evals.py` lines.
- `scripts/repo.py`: remove `evals/` from `TEMPLATE_PATHS`. No behaviour change.
- `.gitignore`: drop the Serena/Graphify block.

Untouched: `scripts/hooks/`, `.claude/settings.json`, `checks.json`, `.github/`, `intent.md`, `spec.md`, every frozen packet, the four remaining skills apart from `sdlc-artifacts`, `LICENSE`, `.gitattributes`.

## Order of work

1. Delete the files listed above with `git rm`. Proof: `git ls-files .agents/skills .claude/skills evals scripts docs` shows no `context7`, `serena`, `graphify`, `evals` or `adoption` entry.
2. Rewrite `docs/host-setup.md` and the `REVIEW.md` paragraph. Proof: neither file contains `Who pushes`, `Trust mode` or `Review modes`; `docs/host-setup.md` is under 90 lines.
3. Edit the remaining documents and `scripts/repo.py`. Proof: `grep -rn "evals\|context7\|serena\|graphify\|adoption\|Who pushes" --exclude-dir=changes --exclude-dir=.git -i .` matches nothing; `.gitignore` keeps `.evidence/` and `__pycache__/`.
4. `python3 scripts/repo.py status --change solo-trim` reports no skill-adapter, hook or scope finding; `python3 scripts/repo.py verify --change solo-trim --full` passes.

## Tests and proof

- `python3 scripts/repo.py verify --change solo-trim --full`: the `control-plane` suite without `test_evals.py` (expected 143 tests, all passing).
- The grep in step 3.
- `python3 scripts/repo.py status`: `status: ok`, every earlier packet still `closure=frozen`.

## Risks and mitigations

- **Something removed is wanted later.** Everything is in git history, and the `enforcement-layers` packet (anchor `449e4e2`) records the eval runner's design. Restoring it is a new change.
- **Dangling references.** The step 3 grep is the acceptance check; the reviewer reruns it.
- **`repo.py status` skill-adapter check.** Deleting a skill and its symlink together keeps the "every `.claude/skills/` entry links to `.agents/skills/<name>`" rule satisfied; step 4 proves it.

## Rollback or recovery

Revert the squash commit; no state outside git is involved.

## Open questions

None. The owner decides at approval whether the eval runner goes with the rest; the plan removes it.
