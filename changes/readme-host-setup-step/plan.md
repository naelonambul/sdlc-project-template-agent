# Implementation Plan

## Summary

The README Quick start tells the reader to remove the template's packets before protecting `main`, but no step protects `main`. The review model depends on that setup: the GitHub App account opens pull requests, and the owner's account reviews and merges them. GitHub does not copy these settings from a template, so a new project that follows the Quick start ends up without them. This change adds the missing step.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `README.md`, Quick start: a new step 3 after the packet removal, and the later steps renumbered to 4 through 8:

  ```text
  3. Configure the repository once, as `docs/host-setup.md` describes: the GitHub App account opens pull requests, your account reviews and merges them, and `main` is protected.
  ```

## Order of work

1. Edit `README.md`. Proof: `grep -n "^[0-9]\. " README.md | sed -n 1,8p` shows steps 1 to 8 in order, and step 3 names `docs/host-setup.md`.
2. `python3 scripts/repo.py status --change readme-host-setup-step` and `python3 scripts/repo.py verify --change readme-host-setup-step --full` pass, then close per `changes/README.md`.

## Tests and proof

The proof is the grep in step 1 and the control-plane tests. This changes documentation only.

## Risks and rollback

- **Private repositories on GitHub Free** cannot use rulesets. `docs/host-setup.md` already covers that case, so the step points there without repeating it.
- Rollback: revert the squash commit.

## Out of scope

- `docs/host-setup.md` itself.
- A new release. This ships with the next one.
