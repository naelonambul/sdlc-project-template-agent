# One-time host setup (GitHub)

GitHub does not copy repository settings, rulesets, or merge settings from a template. Configure each repository created from it separately. None of this changes the repository's contents.

## Merge policy

- Allow **squash merge** only (recommended), with one change per pull request. `repo.py` derives each change's closure anchor from the first-parent history of `main`, so merge commits and rebase-merges also work if a project prefers them.
- Keep `main` linear enough that first-parent history is meaningful: no direct pushes that bypass pull requests.
- In the repository settings, allow squash merging only and disable merge commits and rebase merging. The ruleset below also restricts the merge method. The repository setting keeps the merge button consistent with it.
- Optionally, enable automatic deletion of head branches.

## Protect `main` with a ruleset

Where the plan allows it (public repositories, or private repositories on GitHub Pro, Team, or Enterprise), protect the default branch with one ruleset that has **no bypass actors**:

| Rule | Setting | Why |
|---|---|---|
| Restrict deletions | on | |
| Block force pushes | on | first-parent history anchors closures |
| Require a pull request | 1 approval; dismiss stale approvals; require approval of the most recent push; squash only | a push after approval needs a fresh review, and the approver cannot be the last pusher |
| Require status checks | `summary`, source GitHub Actions; branches must be up to date | the validated candidate is the merge candidate; pinning the source stops another integration from posting a `summary` status |

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
      "required_approving_review_count": 1,
      "dismiss_stale_reviews_on_push": true,
      "require_last_push_approval": true,
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

To apply it, either:

- in the UI, go to **Settings → Rules → Rulesets → New ruleset → Import a ruleset**; or
- as the repository owner, run `gh api -X POST repos/OWNER/REPO/rulesets --input main-protection.json`.

`15368` is the GitHub Actions app. Classic branch protection with the same settings is acceptable. The read-only check below cannot fully see classic protection without administration access.

### Review modes

A pull-request author cannot approve their own pull request. `require_last_push_approval` requires approval from someone other than whoever made the most recent reviewable push. So when one identity both pushes and reviews, neither rule can provide a human gate. These modes are **not equivalent**:

| Mode | Setting | Human-review gate |
|---|---|---|
| **Recommended:** separate agent identity | 1 required approval, last-push approval on, as in the JSON above | **Enforced.** The agent identity pushes; the owner approves. |
| Shared identity, with another human reviewer | unchanged: 1 required approval, last-push approval on | **Enforced.** A different authorized human reviews and approves the pull request. |
| Single person, shared identity | `required_approving_review_count: 0` | **None: this is a degraded mode.** |

The single-person shared-identity mode intentionally gives up the enforced human-approval gate. It still enforces:

- the required `summary` check;
- the force-push and deletion blocks;
- the squash restriction.

Approvals then exist only as local `unverified` claims, which are not identity proof. Choose this mode knowingly, record the choice in `docs/` (see Trust mode), and do not treat it as equivalent to the recommended setup.

### Who pushes what

The two GitHub rules interact with the lifecycle in a way that is easy to trip over. Observed on 2026-10-05, on this repository's own pull request #9: the owner ran `repo.py approve` and `repo.py close` locally and pushed both commits. The owner was then the pull-request author (the agent had opened it with the owner's token) and the last pusher, so under the recommended ruleset nobody was allowed to approve, and the merge was blocked until the ruleset was removed.

The lifecycle produces two owner decisions, the approval claim and the acceptance of the closure, and both can be recorded without the owner pushing:

| Mode | Approval claim | Closure and pull request | Review |
|---|---|---|---|
| Separate agent identity | The owner runs `repo.py approve` locally and either commits and pushes it themselves **before** the final push, or tells the agent the digest and lets the agent run it. | The agent commits, pushes and opens the pull request under its own identity. | The owner approves on GitHub: they are neither the author nor the last pusher. |
| Shared identity, another human reviewer | Anyone may push. | Anyone may push. | The other human approves. |
| Single person, shared identity | Anyone may push. | Anyone may push. | No provider approval is possible, whoever pushed last, because the author cannot approve their own pull request. The `summary` check is the only gate. |

The rule of thumb for the recommended mode: **the agent makes the last push.** If the owner has to push after the agent (for example to add a forgotten `closure.json`), the agent pushes once more afterwards, with a real change such as refreshed closure evidence, before the owner reviews.

### Degraded mode without a ruleset

Removing the ruleset altogether is a further step down from the degraded row above: it also drops the required `summary` check, the force-push and deletion blocks, and the squash restriction. If that is the repository's current state, say so in the trust-mode record, keep squash-only in the repository merge settings by hand, and treat the post-merge `push` run on `main` as the authoritative gate, as in the "Required check without enforcement" section.

## Required check without enforcement

On a private repository on GitHub Free, the branch protection and rulesets APIs return 403 ("Upgrade to GitHub Pro or make this repository public"). CI is then **advisory**. The post-merge `push` run on `main`, which runs the full suite and validates closures, is the first authoritative gate on the merged tree.

## Read-only host check

These commands only read. They work with the owner's `gh` login or a read-scoped agent token, and they change nothing. Run them after creating a repository from the template, and whenever host settings change.

```sh
gh api repos/OWNER/REPO/rules/branches/main --jq '[.[].type] | sort'
# expect: ["deletion","non_fast_forward","pull_request","required_status_checks"]
gh api repos/OWNER/REPO/rulesets --jq '.[] | {id, name, enforcement}'
gh api repos/OWNER/REPO/rulesets/ID --jq '{bypass_actors, rules}'
gh api repos/OWNER/REPO --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge}'
```

Compare the output with the ruleset above. Expect:

- the ruleset's `enforcement` to be `active`;
- `bypass_actors` to be empty or null;
- `pull_request` to have:
  - `allowed_merge_methods: ["squash"]`;
  - one required approval (zero only in the declared degraded mode);
  - `dismiss_stale_reviews_on_push` and `require_last_push_approval` set to true;
- `required_status_checks` to contain `summary` with `integration_id` `15368`, and `strict_required_status_checks_policy` set to true;
- the repository merge settings to allow squash only.

Classic branch protection shows up in `rules/branches/main` as an empty list. Check it in the UI instead, or with an administration-scoped token via `repos/OWNER/REPO/branches/main/protection`.

## Optional: credentials for the agent evals

`.github/workflows/agent-evals.yml` runs `scripts/evals.py` against the Claude Code CLI on pull requests that touch agent configuration, weekly, and on demand. It needs a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions). Without it the job prints a notice and does nothing, which is deliberate: forks and most contributors have no key. The workflow is advisory and never part of the `summary` gate, so the secret can be added or removed at any time. Use a key with its own spending limit; every run drives a real model.

## Trust mode

Decide two things explicitly and record the decision in `docs/`:

1. **Does the coding agent use a distinct, constrained GitHub identity?** A pull-request author cannot approve their own pull request. If the agent and the owner share one identity, provider reviews cannot show independent owner approval, whoever made the last push.
2. **Can `main` be enforced?** See above. Record whether a ruleset is active, and if not, which of its protections the repository settings still provide.

| Setup | Approval that may be claimed |
|---|---|
| Shared identity, or no enforcement | `unverified`: digest-bound local claims; staleness detection, not identity proof |
| Distinct agent identity **and** enforced required review plus required `summary` check | Provider-verified approval becomes possible. `repo.py` still reports `unverified`, because the template has no provider-verification path. |

A distinct agent identity without enforcement is useful for provenance but is not verified approval.

## Optional: a constrained agent identity

One way to give the agent a distinct identity for the recommended review mode:

- **Create a GitHub App** owned by the repository owner, with no webhook. Give it these repository permissions only:
  - Contents: read and write;
  - Pull requests: read and write;
  - Metadata, Checks, and Actions: read.

  Do **not** grant Administration, Workflows, or Secrets.
- **What that means for the agent:**
  - It cannot change rulesets or settings.
  - GitHub rejects its pushes that create or modify `.github/workflows/**`, so the owner makes workflow changes.
  - It cannot approve its own pull request as the owner.
- **Install** the App on selected repositories only.
- **Private key.** Keep the App's private key outside every repository, readable only by the owner (mode `0600`). Never commit it, print it, or paste it into agent context.
- **Tokens.** Mint short-lived installation tokens restricted to one repository and to the permissions above. Have the local helper refuse any repository that is not on an explicit allowlist. Installation tokens expire after one hour; never store them.
- **Commit identity.** Commit as `<app-slug>[bot]` with the email `<bot-user-id>+<app-slug>[bot]@users.noreply.github.com`, so authorship shows the App.
- **No bypass.** Never add the App as a ruleset bypass actor.
- **Keep the helper outside the template.** The token helper is host-specific, so it lives outside the template repository. Record which identity and trust mode the project uses in `docs/`.
