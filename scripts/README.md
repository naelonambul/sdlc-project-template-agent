# Deterministic Scripts

Repository-controlled, deterministic behavior. Standard-library Python and Git only, so the control plane runs on any stack.

- `repo.py`: the control plane.
  - `status` computes change state and enforces lifecycle, approval, identity, write-scope, and agent-surface gates.
  - `verify` runs the checks registered in `../checks.json`.
  - `new` creates a change packet from `../changes/_template/` with `base`, `baseline` and the required root copies filled in.
  - `approve` records the owner's digest-bound approval of a chain artifact, in order; `close` writes a candidate `closure.json` with the packet and baseline digests computed. Both refuse rather than write an inconsistent record, and neither changes what `status` accepts.
- `evals.py`: runs the agent regression evals in `../evals/` against whichever harness CLIs are installed, in a scratch copy of the working tree, and writes evidence under `.evidence/evals/`.
- `tests/`: `unittest` fixtures for `repo.py`, `evals.py` and `hooks/guard.py`. Every hard guard has a failing negative case and a passing positive control. Run `python3 -m unittest discover -s scripts/tests -t .` from the repository root.
- `hooks/`: `guard.py`, the agent-neutral in-session guard, which agent-specific hook configuration (`.claude/settings.json`) calls. See `hooks/README.md`.

Do not add placeholder scripts that pretend to validate a stack that does not exist. When a product needs a multi-command check, add a stable wrapper here and register it in `checks.json`.
