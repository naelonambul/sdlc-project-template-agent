# SDLC Project Template

A small, agent-neutral starter repository for an AI-native software development lifecycle.

This template turns the repository itself into the shared control plane for planning, implementation, verification, and review. It is inspired by the AI-Native SDLC playbook and generalizes the artifact-driven workflow so it can be used with different coding agents.

## Core workflow

```text
idea
  -> changes/<id>/  (intent -> spec -> plan, each approved by the owner in order)
  -> implementation + verification, inside the change's write scope
  -> merge accepted intent/spec into the root baseline
  -> closure.json -> pull request -> merge (squash by default)
```

The root `intent.md` and `spec.md` are the durable product baseline. A new product's first change is `product-init`, which establishes them. `python3 scripts/repo.py status` computes every change's stage, freshness, approval and readiness. See `changes/README.md`.

## Quick start

1. Create a new repository from this GitHub template and clone it.
2. Create the `product-init` packet: `python3 scripts/repo.py new <id> --kind product-init --title "<summary>"`. It copies the root `intent.md` and `spec.md` into the packet.
3. Ask an agent to interrogate the idea until the intent is concrete, then approve `intent.md` yourself: `python3 scripts/repo.py approve <id> intent.md --by <you>` records a digest-bound claim for exactly the bytes you reviewed.
4. Draft and approve `spec.md`, then the change's `plan.md`, in that order.
5. Implement only when `python3 scripts/repo.py status --change <id>` reports `readiness=ready`.
6. Run repository-native validation, review against `REVIEW.md`, merge the accepted intent and spec into the root, run `python3 scripts/repo.py close <id> --evidence <ref>`, and open a pull request with `Change-ID: <id>`.

See `.agents/skills/sdlc-artifacts/SKILL.md` for the workflow.

## Repository control plane

- `AGENTS.md`: short, always-relevant repository invariants, gates, commands, and working rules.
- `REVIEW.md`: shared review rubric.
- `intent.md`, `spec.md`: durable product baseline (why, and what must be true).
- `changes/`: one packet per change, with its own plan; `changes/README.md` defines the model.
- `scripts/repo.py`: `status` computes change state and enforces gates; `verify` runs registered checks with routing and evidence; `new`, `approve` and `close` write packet records mechanically. Standard-library Python only.
- `checks.json`: the check registry (exact argv, cwd, timeout, routed paths, required tools, group). `status` warns when product files are tracked but only the template's own check is registered.
- `scripts/hooks/guard.py`: the agent-neutral in-session guard (deny edits to the root baseline, frozen packets, closures and approvals; ask before destructive git). `.claude/settings.json` is the thin Claude Code adapter; `status` checks that it points at tracked, executable scripts.
- `.agents/skills/`: on-demand shared agent procedures and tool policies. `.claude/skills/` holds thin symlink adapters.
- `evals/` and `scripts/evals.py`: agent regression evaluations run against the installed harness CLIs (agent-surface delivery, the guard, the worker brief). Added from observed failures; run by the advisory `agent-evals` workflow, not by the merge gate.
- `docs/`: supporting, reference, and historical documentation only.
- `.github/`: the `Change-ID` pull-request template and the `repository` CI workflow. See `docs/host-setup.md` for one-time GitHub settings.

## Authority model

The root baseline plus approved change packets are the SDLC authority. `docs/` must not override them. Concurrent initiatives are separate change packets; one pull request carries one change.

## Enforcement layers

The repository enforces its rules in three layers, from hard to soft. Soft layers only make violations rare; the hard layer makes them visible.

1. **Hard, after the fact:** `repo.py status` and `verify`, the control-plane tests, and the required `summary` check in CI. These decide. They do not depend on any agent having read anything.
2. **In session:** `scripts/hooks/guard.py`, called from the agent's pre-edit and pre-command hooks. It denies the edits that no change should make by hand and asks the human before destructive git. It is friction and an audit trail, not authentication.
3. **Advisory:** `AGENTS.md`, the skills, `REVIEW.md`, and the evals that regression-test them against a real harness.

## Scope

The template covers Plan, Design, Build, Test and Deploy as a loop of committed artifacts and gates. The Maintain stage (a trigger that invokes an agent with no person in the path and writes what it finds back as a new intent) is out of scope: the `incident` change kind is the entry point a project would wire a monitor or ticket trigger to, and nothing here runs unattended.

## Agent neutrality

SDLC semantics belong to the repository, not to a specific agent interface. Features such as interrogation commands, plan modes, subagents, or agent-specific hooks are optional convenience layers.

CLI and program installation are machine responsibilities. The repository stores how agents are expected to use those tools through version-controlled skills and policies.

Included shared skills:

- `sdlc-artifacts`
- `change-execution`
- `verification-map`
- `repository-quality`
- `context7`
- `serena`
- `graphify`

Optional tool unavailability must not silently change the SDLC gates.

Claude Code discovers these skills through thin `.claude/skills/<name>` symlinks to `.agents/skills/<name>`, runs the guard through `.claude/settings.json`, and loads `AGENTS.md` only when no project `CLAUDE.md` shadows it. The template therefore ships no `CLAUDE.md`. Codex reads `AGENTS.md` and discovers `.agents/skills/` natively, with no adapter, and has no observed hook integration. See `docs/agent-surfaces.md` for the smoke-tested surfaces and known gaps.

## Project initialization

When a project chooses its application stack, establish the repository-native build, test, lint, format-check, and type-check commands. Register each as a check in `checks.json`, and give checks that need a new toolchain their own group and CI job. Then do the one-time GitHub setup in `docs/host-setup.md`. An existing repository adopts the template through `docs/adoption.md` instead of starting with `product-init`.

## Template releases

Template versions are Git tags plus release notes. A downstream project adopts a tag, not a moving `main`; `docs/adoption.md` covers adopting and upgrading. Settings such as branch protection are never inherited from a GitHub template and must be configured per repository.

## Source material

The structure is informed by Anthropic's *The AI-Native SDLC playbook* (August 21, 2026), especially its artifact-driven handoffs, human gates, short always-loaded context, skills, deterministic guardrails, feedback loops, independent verification, PR review policy, and continuous evals.
