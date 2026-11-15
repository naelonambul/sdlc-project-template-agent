# Deterministic Scripts

Repository-controlled, deterministic behavior. Standard-library Python and Git only, so the control plane runs on any stack.

- `repo.py`: the control plane. `../changes/README.md` defines the change model it enforces.
  - `status` computes change state and enforces lifecycle, approval, identity, write-scope, and agent-surface gates. Once a product path is tracked it also requires every `checks.json` gate to be decided, and it validates `../comment-exceptions.json`.
  - `verify` runs the checks registered in `../checks.json`.
  - `new` creates a change packet from `../changes/_template/` with `base`, `baseline` and the required root copies filled in.
  - `approve` records the owner's digest-bound approval of a chain artifact, in order. It refuses rather than write an inconsistent record, and it does not change what `status` accepts.
- `tests/`: `unittest` fixtures for `repo.py` and `hooks/guard.py`. Every hard guard has a failing negative case and a passing positive control. Tests run `repo.py` and `guard.py` as real subprocesses. Run `python3 scripts/tests/run.py` from the repository root: it runs `python3 -m unittest discover -s scripts/tests -t .` and passes only if unittest finished, ran at least one test, and reported `OK`, so a test that ends the process early fails the run. Other arguments go to unittest, for example `-k status` for a focused run.
- `hooks/`: `guard.py`, the agent-neutral in-session guard, which agent-specific hook configuration (`.claude/settings.json`) calls. See `hooks/README.md`.

Python here carries no comments or docstrings, apart from a `#!/usr/bin/env python3` line on a file committed as executable; `tests/test_comments.py` enforces it. Put a fact a comment would have held into a test, a name, an assertion message, or this README.

Do not add placeholder scripts that pretend to validate a stack that does not exist. When a product needs a multi-command check, add a stable wrapper here and register it in `checks.json`.
