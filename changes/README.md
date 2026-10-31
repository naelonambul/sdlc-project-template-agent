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
| `incident` | plan | spec | yes; the plan starts with a reproduction that fails on the base (see the `sdlc-artifacts` skill, Incidents) |
| `architecture` | plan | spec | yes |
| `repository` | plan | none | no: process and tooling only; may not modify an established root intent or spec |

Root `intent.md` and `spec.md` start with the `<!-- sdlc:baseline-unestablished -->` marker. The first product change is a `product-init` change, and it removes the marker when its accepted copies are merged. Until then, kinds that inherit the baseline are blocked. A root `intent.md` and `spec.md` without the marker are already established, and `product-init` is not run again.

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

A `plan.md` claim also carries `"write_scope_sha256"`, so widening the scope after approval makes the claim stale. Pattern order does not matter. `repo.py approve` writes it; re-running `approve` rebinds a changed scope without an artifact edit. A `plan.md` claim without it blocks an open packet with `unbound-scope`. Frozen packets are not affected.

Only the human owner adds a claim, after reviewing exactly those bytes. `python3 scripts/repo.py approve <id> <artifact> --by <owner>` writes it for the current bytes and refuses out-of-order approvals; `repo.py status` prints each artifact's current digest for a claim written by hand. In Claude Code, the in-session guard (`scripts/hooks/guard.py`) denies file-tool edits to `approvals` and asks before an agent runs `approve`; elsewhere `status` detects a malformed or stale claim after the fact.

A digest-bound claim yields `approval=unverified`. The digest detects staleness and accidental mismatch. **It is not identity proof**: anyone, an agent included, can compute it. A claim without `sha256` counts as `none`. In solo/manual mode `unverified` is enough for readiness.

`verified` is reserved for a provider path that proves a distinct human approval under merge enforcement the agent identity cannot bypass. The template has no such path, so it never reports `verified`.

An agent-side hook or tool policy that refuses agent edits to `approvals` adds friction and an audit trail. It is still not authentication, because an agent that can edit the policy can bypass it.

## Identity and write scope

- **Local.** `--change <id>` is authoritative. A branch named `change/<id>` or `change/<id>/...`, or a diff that touches exactly one packet, is a convenience inference only. Disagreement or ambiguity blocks.
- **Pull request.** The body carries `Change-ID: <id>`. CI passes it explicitly, and a missing, repeated or unknown ID blocks. One PR is one change: `status` in this mode fails unless the named packet has a candidate closure and the diff touches no other packet except `changes/_template/`.
- **Scope.** Every changed path between the base (the PR base, or the merge-base with the baseline branch) and the candidate must fall inside `changes/<id>/` or match a `write_scope` pattern (`*`, `?`, `**`, trailing `/`). Patterns are relative POSIX paths with no `.` or `..` segments. `repo.py new` adds each root artifact the packet carries, so its approved copy can replace the root.

## Lifecycle

The ordered path for every change, with what `python3 scripts/repo.py status --change <id>` reports:

| Step | Action | Expected status |
|---|---|---|
| 1 | Create the packet; draft artifacts in chain order | `stage=<first unapproved artifact>`, `readiness=blocked` |
| 2 | The owner approves each artifact in order with `repo.py approve`; the agent commits and pushes the claim | after the last: `stage=implementation readiness=ready` |
| 3 | Implement inside `write_scope`; run `repo.py verify --change <id>`, and `--full` before closing | unchanged |
| 4 | Merge accepted change-local `intent.md`/`spec.md` into the root; verify again | unchanged |
| 5 | Add a candidate `closure.json` citing the step 4 evidence | `stage=closed freshness=current readiness=ready closure=candidate` |
| 6 | The agent commits (`git add` the new `closure.json`), pushes, and opens one pull request with `Change-ID: <id>` | the CI `status` job validates the candidate and fails without one |
| 7 | CI `summary` must pass on the head that contains `closure.json`; record the result in the pull request | unchanged |
| 8 | The owner reviews the pull request and squash-merges it | — |
| 9 | The post-merge `push` run on the baseline branch passes; confirm the anchor | `stage=closed freshness=frozen closure=frozen`, anchored at the merge (squash) commit |

Evidence rules:

- **Cite only existing evidence.** A closure cites only evidence that exists when it is written, normally the local `verify` evidence from step 4. `close` refuses unless at least one reference is a `repo.py verify --change <id>` evidence file from a full run: complete, every check in `checks.json` `passed`, HEAD as its `source.commit`, and a `source.tree_sha256` that matches the current files. Any edit after `verify` needs a new `verify`. The digest covers paths, modes and content. It leaves out `.evidence/` and the change's own `closure.json`, so writing the closure does not invalidate its evidence. `close` records it as `tree_sha256`, and `status` reports `closure-stale` when a candidate's files no longer match, including on a branch that is behind the baseline, because CI checks the pull request merged with its base. It stops stale evidence, not forgery; CI and owner review stay the gates. Other references may accompany it. It never cites the CI run of its own pull request, which cannot exist yet.
- **CI results go in the pull request.** Record CI results in the pull request description or a comment, not in `closure.json`. The required `summary` check is the merge gate.
- **Fixes after closure.** If CI or review needs another commit after the closure exists, work in this order, so one commit holds the fix and its closure: edit, `repo.py verify --change <id> --full`, `repo.py close <id> --evidence <ref>`, commit. `close` rewrites `evidence`, `tree_sha256`, and any changed `packet_sha256` or `baseline`. No commit is made only to cite a CI run.
- **After merge.** The packet is frozen. Record follow-up work as a new change.

## Closure

To close a change:

1. Merge accepted change-local `intent.md` and `spec.md` into the root by replacing the root file with the packet copy.
2. Run `python3 scripts/repo.py close <id> --evidence <ref>...`. It computes the digests and refuses while an approval is missing or a carried artifact is not yet merged into the root. An evidence reference that is an existing file (normally `.evidence/<run>/evidence.json`) is recorded with its sha256, so a reviewer can match it against the uploaded CI evidence. The result:

```json
{"schema": 1, "baseline": {"spec.md": "sha256:<resulting root digest>"}, "packet_sha256": "sha256:<packet digest>", "tree_sha256": "sha256:<verified tree digest>", "evidence": ["<local verify evidence reference>"]}
```

Rerunning `close` after a fix rewrites the file with fresh evidence. See Lifecycle for when to add the closure and which evidence it may cite.

`baseline` lists exactly the root artifacts the packet carries. `packet_sha256` covers the packet without `closure.json`. The closure never names a commit.

A pull request can only validate a **candidate** closure: approvals current, deltas merged, digests matching the candidate tree, and evidence present. After merge, the **authoritative anchor** is derived from the baseline branch's first-parent history. It is the newest first-parent commit that introduces the `closure.json` on the branch tip: its tree has the file and its first parent's does not. That is the squash commit (the recommended default), the merge commit, or the rebased commit that adds the file.

The change is `frozen` once its digests verify at that anchor. From then on, any byte difference under `changes/<id>/` relative to the anchor is an integrity failure. Later root baseline changes do not stale a frozen change, because it was verified at its own anchor.

A closed packet stays on the baseline branch. Removing its `closure.json` or the whole packet fails `status`, so a pull request cannot do it, and that includes a plain `git revert` of the closing squash commit. To undo a merged change, open a new change that restores the files. The only exception is removing the template's packets in the Quick start, which commits to the baseline branch before it is protected.

Shallow history cannot establish anchors or bases, so it blocks. CI fetches full history.
