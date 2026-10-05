# Changes

Each unit of work is a **change packet**, `changes/<id>/`. The root `intent.md` and `spec.md` are the durable product baseline. There is no root plan: an active plan lives only in its packet.

`python3 scripts/repo.py status` is the index. It computes every packet's state from repository facts and authored claims. Nothing it reports is stored as a writable label.

## Packet contents

| File | Purpose |
|---|---|
| `change.json` | Authored claims only: `id`, `kind`, `base`, the `baseline` digests it was authored against, `write_scope`, and `approvals`. |
| `intent.md` | Full proposed next root `intent.md`. Only for kinds that change intent. |
| `spec.md` | Full proposed next root `spec.md`. Only for kinds that change behavior or contracts. |
| `plan.md` | How the change is implemented and proven. |
| `closure.json` | Created only when the change closes. |

Create a packet with `python3 scripts/repo.py new <id> --kind <kind> --title <summary> [--scope <pattern>]...`, run from the change's branch point, because it records `HEAD` as `base.commit`. It creates no branch, commit or approval; `status` remains the judge of the result. Copying `changes/_template/` by hand is the fallback. For a change-local `intent.md` or `spec.md`, copy the current root file and edit the copy. It replaces the root file whole when the change closes, which makes "merged into the baseline" checkable byte for byte.

## Kinds

| Kind | Required | Optional | Inherits root baseline |
|---|---|---|---|
| `product-init` | intent, spec, plan | none | no: establishes it |
| `intent` | intent, plan | spec | yes |
| `behavior` | spec, plan | none | yes |
| `implementation` | plan | none | yes |
| `incident` | plan | spec | yes |
| `architecture` | plan | spec | yes |
| `repository` | plan | none | no: process and tooling only; may not modify an established root intent or spec |

Root `intent.md` and `spec.md` start with the `<!-- sdlc:baseline-unestablished -->` marker. The first product change is a `product-init` change, and it removes the marker when its accepted copies are merged. Until then, kinds that inherit the baseline are blocked. An existing product whose root `intent.md` and `spec.md` have no marker is already established: it adopts the template through the template release's `docs/adoption.md`, not through `product-init`.

## Computed state

```text
stage:      intent | spec | plan | implementation | closed
freshness:  current | stale | frozen
approval:   none | unverified | verified
readiness:  blocked | ready
closure:    none | candidate | invalid | frozen
```

- **Order.** Approvals follow `intent -> spec -> plan`, both in chain position and in timestamp order. A downstream approval without its upstream approval blocks.
- **Freshness.** `stale` means a recorded `baseline` digest no longer matches the root file, or an approval is bound to bytes that have since changed. A stale change is blocked until it is refreshed and re-approved.
- **Readiness.** `ready` means every chain artifact carries a current approval and nothing blocks. While a change is not ready, only its own packet may change. Any other changed path blocks.
- **Closure.** A `closure.json` on an unmerged branch is a `candidate`, which CI validates. Once the baseline branch contains it, it is `frozen` at its anchor. Any error makes it `invalid`. `stage` becomes `closed` as soon as `closure.json` exists, before merge.

## Approval claims

```json
{"artifact": "plan.md", "sha256": "sha256:<digest printed by status>", "by": "<owner>", "at": "2026-09-23T10:00:00Z"}
```

Only the human owner adds a claim, after reviewing exactly those bytes. `python3 scripts/repo.py approve <id> <artifact> --by <owner>` writes it for the current bytes and refuses out-of-order approvals; `repo.py status` prints each artifact's current digest for a claim written by hand. In Claude Code, the in-session guard (`scripts/hooks/guard.py`) denies file-tool edits to `approvals` and asks before an agent runs `approve`; elsewhere `status` detects a malformed or stale claim after the fact.

A digest-bound claim yields `approval=unverified`. The digest detects staleness and accidental mismatch. **It is not identity proof**: anyone, an agent included, can compute it. A claim without `sha256` counts as `none`. In solo/manual mode `unverified` is enough for readiness.

`verified` is reserved for a provider path that proves a distinct human approval under merge enforcement the agent identity cannot bypass. The template has no such path, so it never reports `verified`.

An agent-side hook or tool policy that refuses agent edits to `approvals` adds friction and an audit trail. It is still not authentication, because an agent that can edit the policy can bypass it.

## Identity and write scope

- **Local.** `--change <id>` is authoritative. A branch named `change/<id>` or `change/<id>/...`, or a diff that touches exactly one packet, is a convenience inference only. Disagreement or ambiguity blocks.
- **Pull request.** The body carries `Change-ID: <id>`. CI passes it explicitly, and a missing, repeated or unknown ID blocks. One PR is one change.
- **Scope.** Every changed path between the base (the PR base, or the merge-base with the baseline branch) and the candidate must fall inside `changes/<id>/` or match a `write_scope` pattern (`*`, `?`, `**`, trailing `/`). Patterns are relative POSIX paths with no `.` or `..` segments.

## Lifecycle

The ordered path for every change, with what `python3 scripts/repo.py status --change <id>` reports:

| Step | Action | Expected status |
|---|---|---|
| 1 | Create the packet; draft artifacts in chain order | `stage=<first unapproved artifact>`, `readiness=blocked` |
| 2 | The owner approves each artifact in order with `repo.py approve`; the agent commits and pushes the claim (see "Who pushes what" in `docs/host-setup.md`) | after the last: `stage=implementation readiness=ready` |
| 3 | Implement inside `write_scope`; run `repo.py verify --change <id>`, and `--full` before closing | unchanged |
| 4 | Merge accepted change-local `intent.md`/`spec.md` into the root; verify again | unchanged |
| 5 | Add a candidate `closure.json` citing the step 4 evidence | `stage=closed freshness=current readiness=ready closure=candidate` |
| 6 | The agent commits (`git add` the new `closure.json`), pushes, and opens one pull request with `Change-ID: <id>` | the CI `status` job validates the candidate |
| 7 | CI `summary` must pass on the head that contains `closure.json`; record the result in the pull request | unchanged |
| 8 | Human review and approval on the provider; squash merge. Under the recommended ruleset the approver must be neither the pull-request author nor the last pusher, so the agent makes the last push | — |
| 9 | The post-merge `push` run on the baseline branch passes; confirm the anchor | `stage=closed freshness=frozen closure=frozen`, anchored at the merge (squash) commit |

Evidence rules:

- **Cite only existing evidence.** A closure cites only evidence that exists when it is written, normally the local `verify` evidence from step 4. It never cites the CI run of its own pull request, which cannot exist yet.
- **CI results go in the pull request.** Record CI results in the pull request description or a comment, not in `closure.json`. The required `summary` check is the merge gate.
- **Fixes after closure.** If CI or review needs another commit after the closure exists, that same commit:
  - re-runs local verification;
  - replaces the closure's `evidence` with the new references;
  - recomputes `packet_sha256` only if a packet file changed, and `baseline` only if a carried root artifact changed.

  `packet_sha256` excludes `closure.json`, so updating `evidence` never changes it. No commit is made only to cite a CI run.
- **After merge.** The packet is frozen. Record follow-up work as a new change.

## Closure

To close a change:

1. Merge accepted change-local `intent.md` and `spec.md` into the root by replacing the root file with the packet copy.
2. Run `python3 scripts/repo.py close <id> --evidence <ref>...`. It computes the digests and refuses while an approval is missing or a carried artifact is not yet merged into the root. An evidence reference that is an existing file (normally `.evidence/<run>/evidence.json`) is recorded with its sha256, so a reviewer can match it against the uploaded CI evidence. The result:

```json
{"schema": 1, "baseline": {"spec.md": "sha256:<resulting root digest>"}, "packet_sha256": "sha256:<packet digest>", "evidence": ["<local verify evidence reference>"]}
```

Rerunning `close` after a fix rewrites the file with fresh evidence. See Lifecycle for when to add the closure and which evidence it may cite.

`baseline` lists exactly the root artifacts the packet carries. `packet_sha256` covers the packet without `closure.json`. The closure never names a commit.

A pull request can only validate a **candidate** closure: approvals current, deltas merged, digests matching the candidate tree, and evidence present. After merge, the **authoritative anchor** is derived from the baseline branch's first-parent history. It is the first commit whose tree contains `closure.json` while its first parent's tree does not. That is the squash commit (the recommended default), the merge commit, or the rebased commit that adds the file.

The change is `frozen` once its digests verify at that anchor. From then on, any byte difference under `changes/<id>/` relative to the anchor is an integrity failure. Later root baseline changes do not stale a frozen change, because it was verified at its own anchor.

Shallow history cannot establish anchors or bases, so it blocks. CI fetches full history.
