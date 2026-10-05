---
name: sdlc-artifacts
description: Manage change packets (`changes/<id>/`) and the root `intent.md`/`spec.md` baseline. Use when starting a product or a change, interrogating requirements, drafting or revising intent/spec/plan, preparing an owner approval, checking readiness, deciding whether implementation is authorized, or closing a change.
---

# SDLC Artifacts

The lifecycle rules are executable. `python3 scripts/repo.py status --change <id>` computes stage, freshness, approval and readiness, and blocks out-of-order, stale, or out-of-scope work. `changes/README.md` defines the model. This skill covers the judgment around it.

## Start a change

1. Pick an id (lowercase, digits, inner hyphens) and a kind from `changes/README.md`. A new product's first change is `product-init`.
2. From the commit the change starts from, run `python3 scripts/repo.py new <id> --kind <kind> --title "<summary>" [--scope <pattern>]...` (`--with-spec` adds an optional change-local `spec.md`). It writes `change.json` with `base` and `baseline` filled in, the plan skeleton, and copies of the root `intent.md`/`spec.md` the kind requires. Edit those copies, never the root files.
3. Keep `write_scope` to the paths the change needs, as narrow as practical. Without `repo.py new`, copy `changes/_template/` and the root files by hand and fill `base.commit` and the `baseline` digests printed by `status`.
4. Work on a branch named `change/<id>`, and use `Change-ID: <id>` in the pull request.

## Develop each artifact in order

- **Intent.** Interrogate ambiguity before drafting: problem, outcome, affected users and systems, constraints, scope, success criteria, and open questions. Any agent-specific interrogation interface is a convenience only. The intent describes the product and its outcomes. Do not put SDLC process goals in it: CI, pull request, verification, check registration, or closure criteria belong in the change's plan.
- **Spec.** Only after the intent is approved. Turn it into requirements, behavior, design, interfaces, data, dependencies, risks, and acceptance criteria. Carry unresolved questions forward instead of inventing answers.
- **Plan.** Only after the spec is approved, or inherited for kinds that carry no spec. Write it so an agent with no conversation history can implement it: files and components, order of work, proof, risks, and rollback. Challenge the riskiest step. Make each Order-of-work step name the files it changes and one command that proves it, so it can become a unit brief.

Never let a downstream artifact silently contradict an approved upstream one. Surface the conflict to the owner.

## Approval

- Only the human owner approves. Never infer approval from content, Git state, an earlier message, or your own judgment.
- Prefer that the owner runs `python3 scripts/repo.py approve <id> <artifact> --by <name>` themselves. When the owner has explicitly approved exactly the current bytes in this session and asks you to record it, run the same command (in Claude Code the guard asks the human to confirm) and keep the owner's words in `--note`. Never edit `approvals` by hand. Editing the artifact afterwards makes the claim stale, which is intended.
- Whoever runs `approve`, you commit and push the claim.
- Describe local approval honestly: it is `unverified` process metadata. It detects staleness but does not prove identity.

## Implement

- Implement only when `status --change <id>` reports `readiness=ready`. Before that, change nothing outside the packet.
- Read the approved intent, spec and plan throughout. The plan is not the only authority.
- To delegate, follow the `change-execution` skill.
- If a material departure from the approved plan is needed, stop, revise `plan.md`, and get a fresh owner approval.
- Never revise an approved upstream artifact to make implementation easier or to justify code after the fact.

## Close

Follow the Lifecycle and Closure sections of `changes/README.md`:

1. Verify locally (`repo.py verify --change <id>`, and `--full`). When the change touches `AGENTS.md`, a skill or the guard, also run the probes in `docs/agent-surfaces.md` once and record the result there.
2. Merge accepted change-local `intent.md`/`spec.md` into the root (`cp changes/<id>/spec.md spec.md`) and verify again.
3. Run `python3 scripts/repo.py close <id> --evidence <ref>...`, citing only that existing local evidence. `status` then reports `stage=closed closure=candidate`.
4. Commit (`git add` the new `closure.json`; `commit -a` does not pick up new files), push, and open the pull request. CI `summary` must pass on the closure-containing head. Record CI results in the pull request, never in the closure.
5. After human review and a squash merge, confirm `status` on the baseline branch reports `freshness=frozen closure=frozen`.

Fixes after the closure exists rerun `close` with fresh evidence in the same commit; see `changes/README.md`, Lifecycle. After merge the packet is frozen: never edit it again. Record follow-up work as a new change.
