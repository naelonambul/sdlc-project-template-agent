# One-time host setup (GitHub)

GitHub does not copy repository settings, rulesets, or merge settings from a template. Configure each repository created from it separately. None of this changes the repository's contents.

This repository is run by one owner, who approves artifacts with `repo.py approve`, reviews each pull request, and merges it. GitHub cannot add a second human to that loop: a pull-request author cannot approve their own pull request, and the agent pushes under the owner's identity. So the host enforces history and CI, not review.

## Merge policy

- Allow **squash merge** only, with one change per pull request. `repo.py` derives each change's closure anchor from the first-parent history of `main`, so merge commits and rebase-merges also work if a project prefers them.
- Keep `main` linear enough that first-parent history is meaningful: no direct pushes that bypass pull requests.
- In the repository settings, allow squash merging only and disable merge commits and rebase merging.
- Optionally, enable automatic deletion of head branches.

## Optional: protect `main` with a ruleset

Where the plan allows it (public repositories, or private repositories on GitHub Pro, Team, or Enterprise), one ruleset with **no bypass actors** keeps the history and the CI gate honest:

| Rule | Setting | Why |
|---|---|---|
| Restrict deletions | on | |
| Block force pushes | on | first-parent history anchors closures |
| Require a pull request | 0 approvals; squash only | every change goes through a pull request the owner reads |
| Require status checks | `summary`, source GitHub Actions; branches must be up to date | the validated candidate is the merge candidate |

The `summary` job of the `repository` workflow fails unless every other job succeeded.

Import-ready ruleset (`main-protection.json`):

```json
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_last_push_approval": false,
      "require_code_owner_review": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["squash"]}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "do_not_enforce_on_create": false,
      "required_status_checks": [{"context": "summary", "integration_id": 15368}]}}
  ]
}
```

To apply it, either go to **Settings → Rules → Rulesets → New ruleset → Import a ruleset**, or run `gh api -X POST repos/OWNER/REPO/rulesets --input main-protection.json`. `15368` is the GitHub Actions app.

Without a ruleset (for example a private repository on GitHub Free, where the rulesets API returns 403), CI is advisory: a red `summary` does not block the merge button. Keep squash-only in the repository settings by hand, read the checks before merging, and treat the post-merge `push` run on `main`, which runs the full suite and validates closures, as the authoritative gate on the merged tree.

## Read-only host check

These commands only read. Run them after creating a repository from the template, and whenever host settings change.

```sh
gh api repos/OWNER/REPO/rules/branches/main --jq '[.[].type] | sort'
# with the ruleset: ["deletion","non_fast_forward","pull_request","required_status_checks"]
gh api repos/OWNER/REPO/rulesets --jq '.[] | {id, name, enforcement}'
gh api repos/OWNER/REPO --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge}'
```

Expect the ruleset's `enforcement` to be `active` with empty `bypass_actors`, `summary` among its required status checks, and the repository merge settings to allow squash only. Classic branch protection shows up in `rules/branches/main` as an empty list; check it in the UI instead.

## What approval means here

`repo.py approve` writes a digest-bound claim that the owner reviewed exactly those bytes. `repo.py status` reports it as `unverified`: it detects a stale or edited artifact, and it does not prove who ran the command. With one person and one GitHub identity there is no provider path that could prove more, and the template does not pretend otherwise. The owner's two real decisions are the `approve` claim and the merge.
