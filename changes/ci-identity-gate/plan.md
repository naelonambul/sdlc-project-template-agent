# Implementation Plan

## Summary

The policy from `agent-identity-policy` is advisory: a pull request opened under the owner's login passes every check. This change adds an `identity` job to the `repository` workflow. When the repository variable `AGENT_LOGIN` is set, a pull request whose author is not that login fails `summary`, so it cannot merge.

This is a `repository` change: CI, its invariant test, and host documentation. It changes no `scripts/repo.py`, `checks.json`, or lifecycle semantics.

### Decisions

- **Check the pull request author only.** The author comes from GitHub, so a commit message or Git config cannot forge it.
- **No commit-author check.** The App cannot push `.github/workflows/**`, so a legitimate pull request can hold the owner's commit, and author metadata is forgeable anyway.
- **No last-pusher check in CI.** The ruleset's `require_last_push_approval` already refuses the owner's approval when the owner pushed last. A CI check would also be unreliable, because the workflow re-runs on `edited`, where the event's sender is whoever edited the body. In the target stage, with 0 approvals, nothing checks the last pusher; that is an accepted limit of this change.
- **Unset `AGENT_LOGIN` passes with a notice.** The template must work before the App exists, and for an adopter who uses none. Setup makes the variable a required step for a repository with an agent identity.
- **The job always runs, with no job-level `if:`.** A skipped job would fail `summary`, and `test_no_job_is_skipped_by_condition` forbids it. On `push` the step exits successfully.
- **The check stays inline in the workflow, not in `scripts/`.** The App cannot change the workflow, so the agent cannot weaken its own gate.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `.github/workflows/repository.yml`: the `identity` job, and `identity` in `summary`'s `needs`.
- `scripts/tests/test_workflow.py`: one invariant test.
- `docs/host-setup.md`: the variable, and the corrected owner-token paragraph.

### Text for `.github/workflows/repository.yml`

Add before the `summary` comment:

```yaml
  # Fails a pull request not authored by the agent identity. An unset
  # AGENT_LOGIN passes with a notice; see docs/host-setup.md.
  identity:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - env:
          AGENT_LOGIN: ${{ vars.AGENT_LOGIN }}
          EVENT_NAME: ${{ github.event_name }}
          PR_AUTHOR: ${{ github.event.pull_request.user.login }}
        run: |
          if [ "$EVENT_NAME" != pull_request ]; then
            echo "identity: not a pull request"
            exit 0
          fi
          if [ -z "$AGENT_LOGIN" ]; then
            echo "::notice::AGENT_LOGIN is not set; pull request author not checked"
            exit 0
          fi
          if [ "$PR_AUTHOR" != "$AGENT_LOGIN" ]; then
            echo "::error::pull request author $PR_AUTHOR is not the agent identity $AGENT_LOGIN"
            exit 1
          fi
          echo "identity: $PR_AUTHOR"
```

Change `summary`'s `needs` to `[control-plane-tests, status, verify-core, identity]`.

### Text for `scripts/tests/test_workflow.py`

Add after `test_summary_needs_every_job_and_requires_success`:

```python
    def test_identity_job_compares_the_author_with_the_variable(self):
        self.assertIn("identity", self.jobs)
        self.assertIn("AGENT_LOGIN: ${{ vars.AGENT_LOGIN }}", self.text)
        self.assertIn("PR_AUTHOR: ${{ github.event.pull_request.user.login }}", self.text)
        self.assertIn('[ "$PR_AUTHOR" != "$AGENT_LOGIN" ]', self.text)
```

### Text for `docs/host-setup.md`

Replace the paragraph starting "A session that pushes under the owner's own token" with:

```markdown
CI enforces the author. When the repository variable `AGENT_LOGIN` is set, the `identity` job fails any pull request not authored by that login, and with it `summary`. A session that pushes under the owner's own token breaks the last-push rule: the owner is then the last pusher and cannot approve. Let the bot push last. To work without the agent, the owner clears the variable, which disables the check.
```

Add at the end of "Which commands the agent uses", replacing "This is a rule for the agent, not a control. Nothing here stops a session from using the owner's login, so `repo.py approve` claims, the required checks and the owner's review stay the gates.":

```markdown
The command path is a rule for the agent, and CI checks its result. Set `AGENT_LOGIN` to the App's login once the App exists; this is a required step for a repository with an agent identity:

```sh
gh variable set AGENT_LOGIN --body '<app-slug>[bot]' --repo OWNER/REPO
```

Unset, the `identity` job passes with a notice. The check covers the pull request's author. It does not cover commits, or a session that only reads with the owner's login, so `repo.py approve` claims and the owner's review stay gates.
```

Add to the commands in "Read-only host check":

```sh
gh variable get AGENT_LOGIN --repo OWNER/REPO
```

## Order of work

The App cannot push the workflow, so the owner makes that one commit. Each other step is one coordinator edit, so the route is single agent.

1. Edit `docs/host-setup.md` and `scripts/tests/test_workflow.py`; commit and push. Proof: `grep -c 'AGENT_LOGIN' docs/host-setup.md` prints at least `1`.
2. Edit `.github/workflows/repository.yml` in the working tree, without committing it. Proof: `python3 -m unittest scripts.tests.test_workflow` passes.
3. The owner commits and pushes that one file on this branch under their own login. Proof: `git log -1 --format=%an -- .github/workflows/repository.yml` on the branch names the owner.
4. Pull the branch, run `python3 scripts/repo.py verify --change ci-identity-gate --full`, then close per `changes/README.md`.
5. The agent pushes the closure last and opens the pull request as the App. Proof: the `identity` job passes with the unset-variable notice, and `summary` passes.
6. After merge, the owner runs `gh variable set AGENT_LOGIN --body 'mini26-agent[bot]'`.
7. Prove both outcomes on real pull requests. An App-authored draft passes `identity`. A draft opened by the owner fails `identity` and `summary`. Close both unmerged and delete their branches.

## Tests and proof

- `python3 scripts/repo.py status --change ci-identity-gate` passes, which shows every changed path is inside `write_scope`.
- `python3 scripts/repo.py verify --change ci-identity-gate --full` reports no `failed`, `blocked`, or `not-run` check.
- `test_summary_needs_every_job_and_requires_success` fails unless `identity` is in `needs`.
- Step 7 is the real proof, because the invariant test reads text and cannot prove GitHub's behavior. It runs after merge, so it cannot be closure evidence. Its result goes in a comment on the merged pull request.

## Risks and mitigations

- **The App's login format.** `gh` shows `app/mini26-agent`, while the event payload should carry `mini26-agent[bot]`. A wrong value fails every pull request. Step 7 catches it, and clearing the variable recovers.
- **Self-approval.** If the owner pushes last, they cannot approve. Step 5 has the agent push last.
- **A later bot push may be refused.** GitHub could reject the closure push on a branch holding a workflow commit. Then the owner pushes the closure, and the merge needs the handling in Open questions.
- **Updating the branch from `main`** under the strict status policy may touch workflow history, which the App cannot always push. If so, the owner updates the branch and the agent pushes once more.
- **Pull requests from forks and other bots.** A Dependabot or fork author fails the check while the variable is set, and fork runs may not receive repository variables. This template has neither today. A later change can add an allowlist.
- **The check is off while the variable is unset**, and anyone with admin rights can clear it. The ruleset does not cover variables. The read-only host check shows its value.

## Rollback or recovery

Clearing `AGENT_LOGIN` disables the check at once, with no commit. Before merge, drop the branch. After merge, open a new change that removes the job; the owner pushes the workflow part.

## Open questions

- If the App's closure push is refused in step 5, the owner would be last pusher and could not approve. No repository-side fix exists without a ruleset change, so the plan stops there and asks the owner.
