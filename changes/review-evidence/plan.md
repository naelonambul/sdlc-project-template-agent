# Record change reviews and performance evidence

## Summary and issue proposal

Use the workflow plan → pre-implementation review and owner approval → implementation → verification → final review. Pre-implementation review informs the existing approval gate. After testing, record the final review in `changes/<id>/review.md` with the reviewed implementation commit, findings, disposition, and references to that commit's verification evidence. Keep raw check logs and benchmark output in `.evidence/`. Include material results in the PR and link to reviewer-accessible evidence when available.

For PRs claiming better performance, throughput, or resource use, define the baseline revision, workload, environment, metrics, and acceptance criteria in the plan. Compare baseline and candidate under the same conditions, recording both values and any errors or output consistency checks. Review the results against the approved criteria.

## Files and components that change

- `changes/README.md` describes the workflow and the review record authored after implementation and verification.
- `REVIEW.md` defines the review record and conditional benchmark requirements.
- `.github/pull_request_template.md` extends Verification with the review link and an optional before/after evidence section.
- `changes/review-evidence/review.md` demonstrates the new process with this change's own findings and evidence references.

## Order of work

1. Update `changes/README.md` and `REVIEW.md` to explain the existing owner approval gate, when to write and refresh the final review, and how to cite evidence. For performance claims, specify `.evidence/benchmarks/<change-id>/<run-id>/` for raw benchmark captures and include the comparison in the review record and PR. Inspect the wording with `git diff -- changes/README.md REVIEW.md`.
2. Update `.github/pull_request_template.md` with concise prompts for verification evidence, the final review link, and benchmark evidence when applicable. Confirm that its first line still reads `Change-ID: replace-with-change-id` by running `head -n 1 .github/pull_request_template.md`.
3. Commit the approved packet and implementation under the agent identity and run `python3 scripts/repo.py verify --change review-evidence --full` on that commit. Review that revision and write `changes/review-evidence/review.md` citing its commit and verification run. Commit the review record and run `python3 scripts/repo.py status --change review-evidence` and full verification on the resulting HEAD. Report the final HEAD's verification run in the PR. If implementation changes after review, verify and review the updated implementation, refresh the record, and verify the new final HEAD.

## Expected byproducts and cleanup

Repository verification creates agent-owned run logs and `evidence.json` under `.evidence/<run-id>/`. Retain the cited runs as local evidence and reference accessible CI artifacts or include decision-critical summaries in the PR. Removing a cited run would lose its raw proof. No other byproducts are expected.

## Tests and proof

Run `git diff --check` before committing. Confirm status and the `control-plane` check in full verification accept an active packet containing `review.md`. Read the three revised documents together and verify that a reviewer can locate the plan, final review, and supporting evidence from the PR. The change itself makes no performance claim.

## Risks and mitigations

Local evidence paths may be inaccessible in GitHub. Put the material results in the PR and link to accessible artifacts when available. Apply the workflow to new changes using the existing packet scaffolding, approval, and merge rules. If the existing status or verification checks reject the review record, revise the scope and plan for owner approval before changing tooling.

## Rollback or recovery

Use a follow-up repository change to revert the workflow documentation and PR template.

## Open questions

None.
