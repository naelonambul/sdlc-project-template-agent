# Implementation Plan

## Summary

Resolve issue #59 with a plan-first approach, incorporating the owner's direction of 2026-11-19: identify expected byproducts and their cleanup or retention in the implementation plan before work starts. When unexpected byproducts appear, analyze the consequences of deleting them and notify the owner or disclose the risks in the pull request. Preserve uncertain items until resolved.

The current plan template has no byproduct section, and the SDLC skill has no post-PR cleanup procedure. Add a small section to the existing template and concise guidance to the existing skill, covering planning, unexpected discoveries, PR disclosure and closeout. This is a repository-process change; root intent/spec, lifecycle gates and executable behavior remain unchanged. No automatic deletion tool, new mandatory ledger or new approval gate is introduced. Ownership and retention require judgment across files and external resources, so prose is appropriate.

## Files and components that change

- `changes/_template/plan.md`: add an expected-byproducts and cleanup section, prompting location/resource identity, purpose, ownership, cleanup or retention, timing and deletion risk. Allow an explicit “none expected” for work that produces none; avoid fixed placeholder paths that agents might delete blindly.
- `.agents/skills/sdlc-artifacts/SKILL.md`: extend Plan guidance to require that section; add handling for unexpected byproducts during implementation and concise closeout guidance under Finish. Reuse Pre-existing local files rather than duplicating or weakening its rules.
- `docs/agent-surfaces.md`: record actual dated discovery probe outcomes for the changed skill.
- `changes/closeout-byproducts/`: plan, metadata and human-readable review/verification results. No raw generated analysis metadata is committed. Pre-approval review results go in `review.md`; post-approval scenario results and verification evidence are reported in the PR/chat rather than appended to the approved plan.

## Order of work

1. Independently review these exact plan bytes and the same source context with Astra, Argon and Neon against REVIEW.md. Record input digests, findings and dispositions in this packet; re-review material revisions. Present the final plan for owner approval. Proof: `python3 scripts/repo.py status --change closeout-byproducts` reports a current plan awaiting approval, then readiness=ready before edits outside the packet.
2. Edit `changes/_template/plan.md` and the skill's Plan guidance: before implementation, list expected implementation/testing/verification byproducts, including temporary files, scratch checkouts, processes and external tool resources where relevant. For each, identify its location or bounded creation pattern, purpose/owner, removal or retention decision, timing and deletion impact. Required evidence and intentional backups are retained. Planning a cleanup does not authorize deleting shared or in-use resources, expand write_scope, or override tool-specific permissions. Proof: `git diff --check` and manual planning scenarios reported in the PR/chat.
3. Edit the skill's Implement/Finish guidance: inventory actual byproducts against the plan. For unexpected items, assess origin/ownership, current users/dependencies, potential data/work loss, evidence/backup retention and recoverability before deleting. For pre-existing local files, follow Pre-existing local files; for pre-existing processes or external resources, establish origin and use through resource-specific read-only queries and preserve uncertain resources pending the owner’s decision. Notify the owner promptly when deletion could lose work, affect shared/in-use resources or requires an owner decision; leave such items unchanged pending that decision. Disclose unresolved items and deletion risks in the PR when opening or updating it. A PR disclosure alone is not permission to delete. An unexpected item proven task-owned, disposable, unused and safe may be removed within existing authorization, with the assessment and disposition reported to the owner or in the PR. Material changes to implementation scope or plan still require revised approval under existing rules. Proof: `git diff --check` and manual unexpected-item scenarios.
4. Add a short post-closure procedure in `.agents/skills/sdlc-artifacts/SKILL.md`: confirm the PR’s final state (merged versus closed without merge) on the host using the agent identity path selected by docs/host-setup.md; if unavailable, ask the owner for confirmation and never fall back to owner credentials; reconcile planned and actual resources, then remove only clearly work-owned disposable unused items via supported tool paths. Preserve required verification evidence, intentional backups, shared/in-use resources and anything uncertain. A PR closed without merge does not make unmerged work disposable. Keep the active checkout and originating session intact while in use. Report removals, retained items and reasons, including a no-removal result. Discoveries after PR closure are reported in the originating chat; they must not disappear into an obsolete PR disclosure. Cleanup is a follow-up, not a condition for computing merged state. Proof: `git diff --check` and manual closeout scenarios reported in the PR/chat.
5. Create a fresh scratch repository with `git clone` (preserving Git metadata and relative skill symlinks), copy the candidate skill into it, confirm source and scratch skill digests match, and run the probes documented in `docs/agent-surfaces.md`, including Claude's shadowing negative case. Record actual versions and outcomes there. Keep raw logs outside tracked source. Proof: documented `claude -p` and `codex exec --sandbox read-only` probes reach terminal results and show the expected repository instruction/skill discovery; report failures rather than asserting support.
6. Review against REVIEW.md. Run `python3 scripts/repo.py status --change closeout-byproducts` and `python3 scripts/repo.py verify --change closeout-byproducts --full`. Report results in the PR/chat without editing the approved plan. Commit final source and permitted records as the agent, then run status and full verification again on that final HEAD before pushing; any later commit requires another full verification before push or result reporting. Put that final evidence path/result in the PR. Push and open a PR as the agent through docs/host-setup.md, with `Change-ID: closeout-byproducts` and `Closes #59`. Include unresolved byproducts and deletion risks in its body. The owner reviews/merges. After confirmed closure, apply the procedure to this task's eligible byproducts and report actual removals/retentions.

## Expected byproducts and cleanup

This change itself follows the proposed approach. These are bounded candidates, not blanket deletion instructions; verify actual identity and non-use at closeout.

| Resource/location | Purpose and ownership | Disposition and timing | Deletion risk |
|---|---|---|---|
| This change packet and final source edits | Durable repository deliverables, this change | Retain in Git | Loss of change/review history |
| `.evidence/<run>/` created by verification | Required validation evidence, this change | Retain locally, uncommitted | Loss of proof; never treat as disposable merely because generated |
| Uniquely task-created review bundle directories under the system temporary directory; actual identities recorded at creation in session logs | Identical reviewer input snapshots and raw outputs, this chat | Retain supporting review evidence until results/digests are recorded and retention needs resolved; remove only disposable copies after closure | Loss of reproducibility if sole evidence is deleted; live reviewers may still use inputs |
| Fresh uniquely named scratch clone for CLI probes, actual path recorded at creation in the originating session log | Disposable probe workspace, this change | Remove after closure only after probes exit and required outputs are retained separately | Uncaptured outputs or still-running harnesses; inspect for unique work before removal |
| Reviewer/probe subprocesses and delegated reviewers created by this chat | Review/verification execution | Let finish; close completed delegates when no longer needed; stop only task-owned obsolete runs | Interrupting active work or losing incomplete output |
| Raw probe logs in a task-created temporary directory, actual path recorded at creation in the originating session log | Verification support evidence | Retain required evidence; remove disposable duplicates only after closure | Loss of probe proof if unique logs are removed |
| `change/closeout-byproducts` branch | This change’s Git work | Retain while active or unmerged; consider supported cleanup only after confirmed merge and non-use | Loss of unmerged or active work |
| Current checkout, shared caches, credentials, intentional backups, pre-existing local files | Active/shared/owner resources | Retain; outside disposable inventory | Work loss, shared-tool breakage, loss of recovery material |

Review/probe inputs and raw outputs that are the sole supporting evidence remain retained locally; a digest or summary alone is not a replacement for that evidence. Copies are disposable only when the supporting evidence is preserved elsewhere and no live consumer depends on them. Temporary creation patterns identify candidates; they are never deletion globs.

## Tests and proof

- No executable behavior changes or new test code. Keep registered checks unchanged; full verification must be complete with no failed, blocked or not-run checks.
- Planning scenarios: expected scratch artifact has ownership/timing/risk; required evidence has retention; no expected byproducts can be stated explicitly.
- Unexpected-item scenarios: a clearly disposable task-owned file has a recorded low-risk disposition; an unknown pre-existing ignored file remains pending origin/owner resolution; a shared or in-use resource remains; evidence or backup remains; potential work loss is promptly reported to the owner; unresolved risks appear in the PR; PR disclosure never substitutes for authorization.
- Closeout scenarios: PR closure is verified; planned items are rechecked for current use; closed-unmerged work remains; an active session/checkout remains; actual removals and retentions are reported even when nothing is removed; post-closure discoveries reach the owner.
- Record the actual wording supporting each scenario. CLI discovery probes prove availability, not universal agent obedience to judgment-based guidance.

## Risks and mitigations

- Planned cleanup can become stale: reconcile against live state before removal; names/age/ignore status alone prove neither ownership nor disposability.
- Risk disclosure might be mistaken for consent: explicitly retain unresolved/high-risk items pending the existing owner decision requirements.
- Excess process for small changes: use one short section in the existing plan and ordinary chat/PR reporting; no new artifact or gate.
- Plan or scope changes after approval: follow existing material-departure and digest-bound reapproval rules.
- Unknown harness availability or probe failure: report observed results and investigate; do not claim a passing surface without proof.

## Rollback or recovery

Before merge, revise the plan and obtain fresh approval for material changes. After merge, revert through a new repository change. This implementation adds guidance and deletes no pre-existing resources. Later cleanup must preserve uncertain resources and use supported tool paths; do not promise recovery for an irreversible deletion.

## Open questions

None about scope. The reviewed final plan still requires the owner's digest-bound approval before implementation under AGENTS.md and the sdlc-artifacts skill.
