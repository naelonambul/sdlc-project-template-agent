# Adopting the template in an existing repository

This guide is for a repository that already has code, history and, usually, product documents. A new repository created from the template follows the quick start in the root `README.md` instead.

Adoption is one ordinary change: a `repository`-kind change packet, approved by the owner and reviewed as a pull request. It installs the control plane and leaves the product's existing authority untouched. It creates no approvals for documents that were accepted before adoption.

Below, `<release>` means a checkout of the release being adopted (step 2). Read this guide and every other template document there. The adopted repository does not get the template's `docs/`.

## 1. Choose the path

`repo.py` treats a root `intent.md` or `spec.md` as an **established baseline** when the file exists and does not contain the marker `<!-- sdlc:baseline-unestablished -->`.

- **Existing product.** The repository has root `intent.md` and `spec.md`, and the owner treats them as the product's authority. Adopt without a `product-init`: the files stay byte-for-byte as they are, and later changes inherit them through `baseline` digests.
- **No usable baseline.** The repository has neither file, or has files the owner does not treat as authoritative. Do the adoption below, but also:
  - move any non-authoritative originals to `docs/history/`;
  - copy the template's two placeholder files, which carry the marker;
  - add `--scope intent.md --scope spec.md` in step 3.

  Then make the first product change a `product-init`, which establishes them.
- **Only one of the two files exists.** Inheriting kinds need both files established. Settle this before adopting: either the owner provides the missing file and it is committed as part of the product's history, or follow the no-usable-baseline path.

Only the root `intent.md` and `spec.md` are digest-tracked. If requirements also live in other files, they are not protected by the lifecycle gates. The owner decides whether a later `behavior` or `intent` change folds them into `spec.md` or `intent.md`.

## 2. Pin a release

Adopt a release tag, never a moving `main`. Clone the template **next to** the repository, not inside it, and check out the tag:

```bash
git clone https://github.com/<owner>/<template-repo>.git ../sdlc-template
git -C ../sdlc-template switch --detach <tag>
```

Record the tag and its commit in the adoption packet's `plan.md`. That is the only record of which release the repository adopted, and the next upgrade diffs from it. A full clone keeps the old and new tags side by side for that diff.

## 3. Prepare, then create the adoption packet

Check these before creating anything. `status` rejects each one if it is left for later.

- **Untracked output.** `status` counts untracked files as changes. The existing `.gitignore` must cover the project's build and test output, and it must ignore `__pycache__/`, because the template's own control-plane tests write Python bytecode under `scripts/`. If it doesn't, add those rules in a small commit on `main` first.
- **Line endings of the baseline.** Run `git ls-files --eol intent.md spec.md`. If either shows `i/crlf`, you cannot add the template's LF rule for that file during adoption. Git would report the file as modified, and a `repository` change may not modify an established baseline. Leave those two rules out (step 4), and normalize them later inside owner-approved changes: an `intent` change for `intent.md`, and a `behavior` change for `spec.md`.
- **Default branch.** `repo.py` anchors closures on the baseline branch. If it is not `main`, set `baseline_branch` in `checks.json` and the `push` branches in `repository.yml` to match (steps 4 and 6).

Then run the release's `repo.py` from the repository root. It works before `changes/` exists, because it falls back to the plan skeleton shipped with the release.

```bash
git switch -c change/adopt-sdlc-template
python3 <release>/scripts/repo.py new adopt-sdlc-template --kind repository \
  --title "Adopt the SDLC template <tag>" \
  --scope scripts/repo.py --scope scripts/__init__.py --scope scripts/tests/ \
  --scope changes/README.md --scope changes/_template/ \
  --scope .github/workflows/repository.yml --scope .github/pull_request_template.md \
  --scope .agents/skills/ --scope .claude/skills/ --scope .claude/settings.json \
  --scope scripts/hooks/ --scope scripts/evals.py --scope evals/ \
  --scope .github/workflows/agent-evals.yml \
  --scope checks.json --scope AGENTS.md --scope REVIEW.md \
  --scope .gitignore --scope .gitattributes --scope docs/history/ --scope plan.md
```

Adjust the scope to what the plan actually touches:

- add each tracked `CLAUDE.md` that has to change, and any `CLAUDE.local.md` that has to be removed (step 4);
- add each existing workflow file you edit;
- add the paths of anything you retire into `docs/history/`, and the file where you record the trust mode (step 7);
- drop `scripts/hooks/`, `.claude/settings.json`, `scripts/evals.py`, `evals/` and `agent-evals.yml` if the repository chooses not to install the guard or the evals. They are optional layers; `repo.py status` and CI work without them.

On the existing-product path, never include the root `intent.md` or `spec.md`. A `repository` change may not modify an established baseline, and `status` blocks the change if it does.

Write the plan. It should cover the pinned tag and commit, the file lists from step 4, the rules being replaced, the checks to register, what moves to `docs/history/`, and the host setup and trust mode. Then check it with the same external `repo.py`:

```bash
python3 <release>/scripts/repo.py status --change adopt-sdlc-template
```

Before installation, `status` may end in `status: FAILED` because of `surface error` lines about agent surfaces the repository already has, such as a `CLAUDE.md` without an import, or a skill directory under `.claude/skills/`. Those are fixed in step 4, so judge the plan gate from the packet's own lines. Every other error must be resolved first.

The owner approves the exact `plan.md` digest that `status` prints. Record that as a digest-bound claim in `change.json` (see "Approval claims" in `<release>/changes/README.md`), and continue only when the packet shows `readiness=ready`. From step 7 on, `status` must end in `status: ok`. There is no approval for the existing `intent.md` or `spec.md`, and none is needed: a `repository` change inherits no product baseline.

## 4. Install

Each file falls into one of three groups.

**Copy verbatim from `<release>`.** Never edit these locally, because upgrades replace them whole. If a copy already exists, remove it first and copy fresh, so no stale files survive. That matters most when the repository used an earlier version of these skills.

- `scripts/repo.py`, `scripts/__init__.py` and `scripts/tests/`. If the repository already has a `scripts/` Python package, check for name clashes first.
- `changes/README.md` and `changes/_template/`.
- The core skills and their adapters: `.agents/skills/sdlc-artifacts/`, `change-execution/`, `verification-map/` and `repository-quality/`, plus the matching `.claude/skills/<name>` symlinks (`../../.agents/skills/<name>`). The tool skills (`context7`, `serena`, `graphify`) are optional.
- The in-session guard: `scripts/hooks/` (`guard.py` and its README). Its tests live in `scripts/tests/`, already copied.
- The eval runner, `scripts/evals.py`, and the cases under `evals/` that apply to any repository built on the template: `agents-md-delivered`, `claude-md-shadows-agents-md`, `guard-blocks-root-baseline-edit`, `guard-blocks-approval-edit` and `worker-brief-stays-in-files`. Copy `evals/README.md` with them. Add the repository's own cases from observed failures only.

**Merge by hand, keeping what belongs to the product.**

- **`AGENTS.md`.**
  - Add the template's Authority, SDLC-gate, working-rule and canonical-command sections.
  - Keep the project's own product and engineering rules.
  - **Replace** every rule from an earlier process about authority, acceptance or gates, for example "do not implement until `plan.md` is accepted" or front-matter `status: accepted` gates. Keeping both gives agents conflicting authority.
  - The canonical commands must name the repository's real commands (step 6).
- **Agent surfaces.**
  - Every tracked `CLAUDE.md` must import a tracked `AGENTS.md` in its own directory or an ancestor (for example `@AGENTS.md` at the root, or `@../AGENTS.md` one level down), or be removed.
  - A tracked `CLAUDE.local.md` must be removed.
  - Every entry under `.claude/skills/` must be a symlink to `../../.agents/skills/<name>`. Move a project's own skill into `.agents/skills/<name>/` and link it the same way.
  - `.claude/settings.json`: if the repository has none, copy the release's. If it has one, add the release's `PreToolUse` entries for `Edit|Write|MultiEdit` and `Bash` that run `python3 "$CLAUDE_PROJECT_DIR"/scripts/hooks/guard.py claude`, and keep the project's other settings. Every `scripts/hooks/` script the file names must be tracked.

  `status` reports each violation as an error.
- **`.github/workflows/agent-evals.yml`.** Copy the release's if the repository installs the evals. It is advisory and needs an `ANTHROPIC_API_KEY` secret to do anything; see the host guide.
- **`REVIEW.md`.** Add the template's review passes to any existing review policy, and replace review rules that belong to an earlier process.
- **`.gitignore`.** Add `.evidence/` and `__pycache__/` if they are not there yet.
- **`.gitattributes`.** Add the template's LF rules for `changes/**` and `checks.json`, and for `intent.md` and `spec.md` unless step 3 found CRLF, because approvals bind exact bytes.
- **`.github/pull_request_template.md`.** The first line must be `Change-ID: <id>`.
- **`.github/workflows/repository.yml`.** Start from the release's copy. Change it only to add jobs for extra check groups (step 6) and, if needed, the `push` branch. Pushing a workflow file needs a credential that is allowed to change workflows.
- **`checks.json`.** Start from the release's copy. Keep its `control-plane` entry unchanged, and add the repository's checks (step 6).

**Never copy.** Leave these out entirely:
- the template's `README.md`, `LICENSE`, `docs/` and `evals/`, and its own `changes/<id>/` packets;
- its `intent.md` and `spec.md`, except the placeholders on the no-usable-baseline path.

**Do not edit** the root `intent.md` or `spec.md`. That includes any front matter from an earlier process, such as `status: accepted`. It stays as a historical record.

## 5. Retire the root plan

The template has no root plan: an active plan lives only in its change packet. Move a root `plan.md`, and any migration ledgers or progress logs that served as plans, into `docs/history/` without changing their bytes:

```bash
git mv plan.md docs/history/plan.md
```

## 6. Register the existing checks

Put the repository's existing validation commands in `checks.json`, next to the template's `control-plane` check. Call the native entry points the project already uses, with exact `argv`, `cwd`, `timeout_seconds`, `paths` and `requires`. Do not rewrite them. The `repository-quality` skill describes the fields and how to find the commands.

- **Grouping.** A check that needs only Python 3 and Git can join the template's `core` group. Its CI job already has Python and needs no workflow change. Every other toolchain gets its own `group`:
  - give it a `repo.py verify --group <group>` job in `repository.yml`, which sets up that toolchain;
  - add that job to the `needs` of the `summary` job.

  `status` fails when a group has no job, or a job runs an undeclared group. The control-plane tests also fail when `summary` does not need every job.
- **Zero tests.** A check has to fail on its own when it discovers zero tests. `repo.py` sees only exit codes.
- **Existing CI.** Existing workflows may stay. Only the `summary` job of `repository.yml` becomes the required check.

## 7. Verify, close and merge

```bash
python3 scripts/repo.py status --change adopt-sdlc-template
python3 scripts/repo.py verify --change adopt-sdlc-template
python3 scripts/repo.py verify --full
```

From here, the installed `repo.py` and `changes/README.md` apply. Follow the normal lifecycle:

- add a candidate `closure.json`, with `baseline: {}` because this is a `repository` change;
- commit, and open a pull request whose body starts with `Change-ID: adopt-sdlc-template`;
- after the merge, confirm the packet is `frozen`.

Do the one-time host setup in `<release>/docs/host-setup.md`. Record the trust mode in a file inside the adoption scope, for example under `docs/`. On a private repository without rulesets, CI is advisory, and the post-merge run on `main` is the first authoritative gate.

## 8. After adoption

- Start each product change with `python3 scripts/repo.py new <id> --kind behavior|intent|implementation|...`. It records the current root digests as the change's `baseline`.
- Legacy front matter, or CRLF line endings, may be changed only inside an owner-approved change that carries the file: an `intent` change for `intent.md`, and a `behavior` change for `spec.md`.

## Upgrading to a newer release

An upgrade is one `repository` change, `template-upgrade-<tag>`. Its `write_scope` is the adoption scope, minus anything the repository chose not to install.

1. Fetch the new tag in the template clone from step 2.
2. Diff the verbatim-copied **directories and files** between the old tag and the new one:

   ```bash
   git -C ../sdlc-template diff <old-tag> <new-tag> -- scripts/repo.py scripts/__init__.py scripts/tests scripts/hooks scripts/evals.py changes/README.md changes/_template .agents/skills .claude/skills evals
   ```

   List only the skill directories, adapters and eval cases the repository installed, for example `.agents/skills/sdlc-artifacts .claude/skills/sdlc-artifacts`, instead of the whole `.agents/skills`, `.claude/skills` and `evals`, so skipped optional pieces are not added back. The diff includes files the new tag adds or removes. The repository's copies should equal the old tag's. If they don't, find out why before overwriting.
3. Apply that diff. Re-merge the hand-merged files, including the `control-plane` entry of `checks.json`, the template's jobs in `repository.yml`, the hook entries of `.claude/settings.json` and `agent-evals.yml`, from the new tag's versions. Read the new tag's release notes for any step that needs manual work.
4. Run the control-plane tests and `verify --full`, record the new tag and commit in the plan, and close the change as usual.

There is no upgrade automation. Real upgrades will show whether it is worth adding.
