# Implementation Plan

## Summary

Repositories built on the template have no published way to take later template changes. The brownfield adoption guide, which also held the upgrade steps, was removed in `solo-trim` (#12). Since then each adopter has improvised:

- **dogtailor-v3** wrote a one-off procedure (`changes/sdlc-template-upgrade/plan.md` there). It records its pin as prose (`docs/architecture/SDLC_ADOPTION.md:10`, `51ca588`). Its `scripts/repo.py` and `scripts/tests/test_verify.py` differ from that commit because of a local exit-77 `blocked` rule.
- **saltation**'s `scripts/repo.py` is byte-identical to `51ca588`, but nothing records that.

So both adopters sit on `51ca588`, which is untagged and 17 commits past `v2.3.0`.

This change adds an upgrade path that travels with the adopter and is checked by `repo.py`, not left to prose:

1. **A verifiable pin.** `checks.json` gets an optional key, `"template": {"commit": "<40 hex>", "digest": "sha256:<hex>", "carried": [<path>...]}`. When the key is present, `status` recomputes the digest over the copy-group files that the installed `repo.py` owns, minus the `carried` paths. A mismatch is a new error, `template-drift`. A pin can therefore no longer be silently wrong, as dogtailor's is today.
2. **`repo.py upgrade`.** It is a read-only report and is always run from the target template clone against the adopter's working directory:

   ```
   python3 <clone>/scripts/repo.py upgrade --template <clone> --to <ref> [--from <commit>]
   ```

   An adopter whose own `repo.py` predates the command can therefore run it. The report reads the copy and merge lists and the migrations from the target ref (`git show <to>:...`), never from the adopter's possibly stale copy.
3. **A short `template-upgrade` skill.** It covers only what the tool cannot do: the dry run, the packet scope, the workflow-push handoff, the carry-or-upstream decision for local edits, and the close. It is copied with the other core skills.
4. **Migration entries with a mechanical completeness test.** `.agents/skills/template-upgrade/references/migrations.md` has one `## <change-id>` section per template change that needs adopter action. A template test fails when:
   - a `status` error code appears that is neither in a frozen baseline set nor named by an entry;
   - a heading names no `changes/<id>/` packet.

   `REVIEW.md` prose is not the enforcement.

The oldest supported base is `51ca588`, where both real adopters sit. There is no backfill to `v2.0.0`. Migration entries are written for `scripts-comment-free` (#55) and `codebase-rules-gate` (#56):

- **#55** makes `control-plane` fail on any commented Python under the adopter's `scripts/` (`test_comments.py` scans `git ls-files scripts/*.py`).
- **#56** adds `gates-undecided`, `checks-missing` and `comment-exceptions-invalid`.

No compatibility grace mode is needed: an adopter gets the stricter `repo.py` only by upgrading, and the upgrade packet decides the gates in the same PR. The #56 entry says:

- decide every gate there;
- for `comments` in a repository that already has comments, register a ratchet check that fails only on new comments (`repository-quality` skill) instead of a `none` gate.

**Dependency.** This branch starts from `main` at `4f99969`. Implementation starts only after #56 merges. The branch is then rebased onto `main`, and the plan is revised if #56 changed in review.

## Files and components that change

### `scripts/repo.py`

- **`UPGRADE_COPY`**, the copy group, as exact file paths and directory prefixes:
  - `scripts/repo.py`, `scripts/__init__.py`, `scripts/README.md`;
  - `scripts/hooks/`, `scripts/tests/`;
  - `changes/README.md`, `changes/_template/`;
  - `.agents/skills/{sdlc-artifacts,change-execution,verification-map,repository-quality,template-upgrade}/`, and the five `.claude/skills/<name>` links.
- **`UPGRADE_MERGE`**, the merge group: `AGENTS.md`, `REVIEW.md`, `checks.json`, `.claude/settings.json`, `.github/workflows/repository.yml`, `.github/pull_request_template.md`, `.gitignore`, `.gitattributes`.
- **Ownership is per file.** A file is template-owned when it exists under a copy-group entry in the template tree at the base or the target. An adopter file under a copy-group directory that the template never had, such as `scripts/tests/test_local_*.py`, is local. It is reported as `local` and never touched.
- **`validate_checks`** validates `template`:
  - an object with exactly `commit` (40 hex), `digest` (`sha256:` plus 64 hex), and an optional `carried` list;
  - each `carried` entry is a template-owned copy-group path, is tracked, and appears once.

  Anything else is `checks-invalid`.
- **`template_findings(ctx, config)`.** When the `template` key is present, it recomputes the digest and emits `template-drift`, naming the files that differ. The digest is sha256 over the sorted lines `<path>\0<mode>\0<blob sha>` of the tracked template-owned copy-group files minus `carried`. It is computed from Git's index, so modes and symlinks count. An adopter without the key gets no finding: the key is opt-in until the first upgrade records it.
- **The `upgrade` subcommand.** It runs `git -C <clone>` and reads the adopter only. It writes nothing, and exits 0 unless an input is invalid.
  - **Target.** `--to` is required. It is resolved to a full commit, and the report prints that commit and any tag on it.
  - **Base.**
    - With `--from`, or with the pin, the report verifies the base. It prints how many template-owned copy files match the adopter's bytes out of how many. A base that is not an ancestor of the target is an error.
    - With neither, the report prints the candidate commits with the highest match count, oldest first. It exits 1 asking for `--from`. The base is never guessed silently, because a too-new guess would skip migrations and merge diffs.
  - **Report sections:**
    - `drift`: template-owned files that differ from the base and are not `carried`. These must be resolved before applying.
    - `carried`: carried files, with a `git merge-file -p <ours> <base> <theirs>` recipe for each.
    - `copy`: added, changed and removed template-owned files from base to target. A removed file is listed only if it was template-owned at the base. Mode and symlink changes are included.
    - `merge`: merge-group files that changed from base to target, each with its `git -C <clone> diff <base> <to> -- <file>` and a `git merge-file` recipe.
    - `local`: adopter files inside copy-group directories that the template does not own.
    - `migrations`: entries whose packet `changes/<id>/change.json` was added by a commit in `base..to`, in that order. The template's own history decides this, never PR numbers.
    - `pin`: the new `template` value to record in `checks.json`, computed for the target.
  - **Errors** (exit 1): missing clone, unknown ref, base not an ancestor of the target, no base given.

### Skill and migrations

- **`.agents/skills/template-upgrade/SKILL.md`** (new), plus a `.claude/skills/template-upgrade` link. Steps:
  1. **Report.** Run the command above. Without a pin, take the base from the adopter's own record or from the candidates. Confirm it with the owner when the match is partial.
  2. **Dry run** on a scratch clone. Expect approval and scope findings there, because no packet exists yet. Only the remaining failures are upgrade work.
  3. **Packet.** Create one `repository` change.
     - `write_scope` is the copy files the report lists, plus the merge files it lists, plus `checks.json` always (for the pin and gates), plus any path a migration entry names.
     - The plan records the base, the target, each migration and how it is resolved, and each drifted or carried file and what happens to it.
  4. **Drift.** For each drifted file, choose one:
     - upstream the rule to the template;
     - express it as a registered check or a wrapper outside the copy group;
     - list it in `carried`, where the tool shows the three-way merge every upgrade.

     A drifted file is never silently overwritten.
  5. **Apply** per file, from the report:
     - copy each added or changed template-owned file with `git -C <clone> show <to>:<path>`, keeping its mode and symlink;
     - delete only the files listed as removed;
     - merge the merge group and the `carried` files with the printed recipes.

     Never copy `README.md`, `LICENSE`, `docs/`, the template's `intent.md`/`spec.md` or its `changes/<id>/` packets.
  6. **Migrations.** Do each listed entry.
  7. **Workflow.** If `.github/workflows/repository.yml` changed, the agent identity cannot push it. Follow the adopter's workflow handoff. If it has none, the owner pushes the workflow commit first.
  8. **Close.**
     - Record the printed `template` value in `checks.json`.
     - `status` must be ok and `verify --full` complete.
     - One PR.
- **`.agents/skills/template-upgrade/references/migrations.md`** (new). It has entries for `scripts-comment-free` and `codebase-rules-gate`. Each gives what fails, how it shows in `status` or `verify`, and the action. It states `51ca588` as the oldest supported base.

### Tests and docs

- **`scripts/tests/test_upgrade.py`** (new). Tests use a fixture template clone built by the test and an adopter fixture, with helpers added to `scripts/tests/support.py` if needed. Cases are listed under Tests and proof.
- **`scripts/tests/test_status.py`**: `template` validation and `template-drift` cases.
- **Completeness test**, in `test_upgrade.py`. It runs against the template's own tree and checks that:
  - every `UPGRADE_COPY` and `UPGRADE_MERGE` path exists;
  - every `Reason("error", "<code>")` literal in `repo.py` is in a frozen `BASELINE_ERRORS` set (the six codes on `main` at `4f99969`) or named in a `migrations.md` entry;
  - every entry heading names an existing `changes/<id>/`.
- **`scripts/README.md`**: the `upgrade` command and the `template` key.
- **`README.md`**: one line pointing to the `template-upgrade` skill.
- **`docs/agent-surfaces.md`**: one probe row, because a new core skill is added.
- **Unchanged**: `REVIEW.md` and `AGENTS.md`. Enforcement lives in the completeness test.

## Order of work

0. Wait for #56 to merge, then rebase onto `main`. Proof: `git merge-base --is-ancestor origin/main HEAD`. Revise this plan first if #56 changed in review.
1. Skill stub, link, and `migrations.md`, so later tests can assert the paths exist. Proof: `python3 scripts/repo.py status --change template-upgrade` shows no surface error.
2. `template` validation and `template-drift` in `scripts/repo.py`, `scripts/tests/test_status.py` and `scripts/tests/support.py`. Proof: `python3 -m unittest scripts.tests.test_status`.
3. The `upgrade` command and `scripts/tests/test_upgrade.py`. Proof: `python3 -m unittest scripts.tests.test_upgrade`.
4. The full skill text, `scripts/README.md` and `README.md`. Proof: `grep -n "scripts/repo.py upgrade" README.md scripts/README.md .agents/skills/template-upgrade/SKILL.md`.
5. Dry runs on scratch clones of both adopters, outside this repository. Neither adopter is changed. Proof: the reports, quoted in the PR.
   - **saltation**: `--from 51ca588`. Expected: every template-owned copy file matches, no drift, and migrations `scripts-comment-free` and `codebase-rules-gate`. The `local` list includes its `scripts/dev/` files.
   - **dogtailor-v3**: `--from 51ca588`. Expected: drift in `scripts/repo.py` and `scripts/tests/test_verify.py`, its own skills listed as local or outside the groups, and the same two migrations.
   - **Both without `--from`**: exit 1, with `51ca588` among the candidates.
6. Agent-surface probes for the new skill. Record them in `docs/agent-surfaces.md`.
7. `python3 scripts/repo.py verify --change template-upgrade --full`, an independent review, then the PR.

## Tests and proof

`test_upgrade.py`:

- **Base:**
  - a verified base, from `--from` and from the pin;
  - no base given: exit 1 with candidates, oldest first;
  - a base that is not an ancestor;
  - a missing clone or an unknown ref: exit 1.
- **Copy group:**
  - file additions, changes and removals, including a mode change and a symlink;
  - a file the template removed that the adopter still has, which is listed as removed;
  - an adopter file in `scripts/tests/` that the template never had, which is listed as `local` and not as removed;
  - a target that adds a copy path the adopter's version does not know, which is read from the target.
- **Drift and carried:** drift, a carried file with its merge recipe, merge-group diffs.
- **Migrations:**
  - selected by ancestry;
  - an entry whose packet merged before the base is excluded;
  - skipping two template commits at once lists both entries.
- **Pin:** the printed pin equals what `status` computes after a simulated apply.
- **Read-only:** a content, mode and link snapshot of the adopter and the clone is unchanged after the run, even with a dirty adopter tree.
- **Completeness:** the self-test described above.

`test_status.py`:

- valid pin; a non-object; an extra key; a bad commit or digest;
- a `carried` path that is not template-owned, or is duplicated;
- `template-drift` on an edited copy file;
- no finding when the key is absent.

The full suite, `verify --full` and CI on the PR must pass. Each new test is first seen failing against the pre-change `repo.py`.

## Risks and mitigations

- **`template-drift` turns an adopter red after a hand edit.** That is the intent. The way out is `carried`, which stays visible at every upgrade.
- **The digest depends on the installed `UPGRADE_COPY`.** It is recomputed by the `repo.py` that ships with the pinned version, so the list and the files always come from the same commit.
- **The completeness test cannot see semantic breaks**, such as a new repo-wide test invariant like #55's. The test covers error codes. The skill's dry run catches the rest, and an entry is added when one is found.
- **Scope creep into an apply writer.** Kept out. Real upgrades will show whether it pays.

## Rollback or recovery

Revert the PR. An adopter that recorded a `template` key would get `checks-invalid` only from a future `repo.py` that rejects the key, so the revert also leaves validation tolerant of unknown top-level keys, as on `main` today.

## Later, not in this change

- Upstream dogtailor's exit-77 `blocked` contract into `run_check`, as a separate change, so its `repo.py` can stop being `carried`.
- Shrink the merge group: a reusable workflow for the template's jobs, or a marked template block in `AGENTS.md`.
- An apply command, after two or three real upgrades.
