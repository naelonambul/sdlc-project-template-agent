# Implementation Plan

## Summary

The ticket-to-pull-request loop (an agent reads an issue, reproduces it, fixes it, proves the fix) needs two things the template does not yet state: that an `incident` change starts with a reproduction that fails before the fix and passes after it, and what "drive the product and observe the result" means on each platform. Published practice and research converge on three rules, and this change writes them down where agents read them:

1. **Reproduce first, fail-to-pass.** A fix that passes a reproduction test which failed before the fix is markedly more likely to be correct (SWT-Bench, ReProAgent). The reproduction is the first step of an incident plan and its acceptance criterion.
2. **Structured observation is the oracle; pixels are evidence for people.** Web, mobile and desktop agent tooling (Playwright MCP, Maestro MCP, agent-device, sim-use, OS accessibility APIs) all read accessibility trees or DOM with stable refs and take screenshots as secondary evidence. OCR is a last resort where no accessibility data exists. Backend bugs are observed through status codes, logs, stack traces and traces.
3. **Explore, then freeze.** An agent finds the path interactively, then saves it as a replayable script (a Maestro flow, a Playwright test, a shell script) that becomes a registered check where CI can afford it, and a locally run, evidence-producing drive where it cannot (iOS simulator, desktop apps).

The change adds one reference file with per-platform defaults, wires it into the `verification-map` skill, adds the incident rule to the `sdlc-artifacts` skill, and points to both from `changes/README.md` and `README.md`. No code, check or workflow changes. Drivers and toolchains stay machine responsibilities and product-repository content (`verify-<app>`), as today.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `.agents/skills/verification-map/references/platforms.md` (new): one table and short notes per platform (backend/API, web, desktop, mobile, CLI): how to launch and check readiness, how to drive, what to read as the oracle, what to capture for people, the typical tools, and whether the drive can run in CI or stays local. Plus the observation-priority rule and the explore-then-freeze promotion path (save the drive, register it in `checks.json` with its own group and job when CI can run it, otherwise cite its local evidence).
- `.agents/skills/verification-map/SKILL.md`: Create step 1 and 2 point at `references/platforms.md` for defaults; Evidence bullet states the oracle-versus-evidence rule; a new short "Promote" paragraph under Use describes freezing a successful drive into a script and check; description frontmatter mentions reproduction.
- `.agents/skills/sdlc-artifacts/SKILL.md`: a new "Incidents" subsection under "Develop each artifact in order": the plan's first Order-of-work step is a reproduction drive that fails on the base commit with its evidence recorded, the acceptance criterion is the same drive passing, a reproduction that cannot be made is reported on the ticket and the change stops, and the drive is promoted per the `verification-map` skill.
- `changes/README.md`: the `incident` row of the Kinds table gains "plan starts with a failing reproduction (see `sdlc-artifacts`)".
- `README.md`: the Scope paragraph names the reproduce-first rule as what an `incident` change requires, in one sentence.

## Order of work

1. Write `references/platforms.md`. Proof: the file has one row per platform listed above and names at least the oracle and the human evidence for each; no product-specific command appears in it.
2. Edit `verification-map/SKILL.md`, `sdlc-artifacts/SKILL.md`, `changes/README.md`, `README.md`. Proof: `grep -rn "platforms.md" .agents/skills` matches the two skills; `grep -n "fail" .agents/skills/sdlc-artifacts/SKILL.md` matches the incident rule.
3. `python3 scripts/repo.py status --change incident-verification` reports no skill-adapter or scope finding; `python3 scripts/repo.py verify --change incident-verification --full` passes.

## Tests and proof

- `python3 scripts/repo.py verify --change incident-verification --full` (control-plane suite, 135 tests).
- The greps in step 2.
- The smoke-test procedure in `docs/agent-surfaces.md` is not rerun: it probes delivery of `AGENTS.md` and skill discovery, and this change adds or removes no skill and touches no adapter. State this in the pull request.

## Risks and mitigations

- **Over-prescribing tools.** The reference names typical tools as examples, never as requirements; the product's `verify-<app>` skill decides. Each row says "for example".
- **The rule blocks incidents that cannot be reproduced.** That is intended: an unreproduced fix is a guess. The rule says what to do instead (report on the ticket; a `behavior` or `implementation` change may still add defensive handling, with its own plan).
- **Skill length.** `verification-map/SKILL.md` stays under 80 lines by moving platform detail into the reference file.

## Rollback or recovery

Revert the squash commit; no state outside git is involved.

## Open questions

None.
