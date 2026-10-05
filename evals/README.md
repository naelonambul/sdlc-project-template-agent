# Agent Evals

Regression evaluations for repository agent behavior and configuration, run against a real harness CLI (`claude`, `codex`) by `scripts/evals.py`.

Deterministic checks (`scripts/repo.py`, its tests, CI) come first. Add an eval only when a real agent failure occurs that those checks cannot cheaply express, for example:

- a repeated agent mistake or a review finding that should not recur;
- an incident or escaped defect caused by agent behavior;
- a change to `AGENTS.md`, skills, hooks, or agent-driving configuration that needs regression coverage.

Each eval is the smallest case that reproduces the failure, plus the checks that make a result acceptable. Prefer real discriminating cases over synthetic filler.

## Cases

A case is a directory `evals/<id>/` holding one `eval.json`; the directory name is the case id. The runner copies the working tree (tracked and untracked, unignored files; symlinks preserved) into a scratch directory with a fresh git history, writes the case's `files`, runs each harness non-interactively there, and compares file digests before and after. The real checkout is never touched.

| Field | Meaning |
|---|---|
| `schema` | Always `1`. |
| `description` | Optional. What the case proves and what a failure means. |
| `harnesses` | Non-empty subset of `["claude", "codex"]`. |
| `prompt` | The non-interactive prompt. |
| `files` | Optional. Relative POSIX path to text content, written into the scratch copy after its commit. |
| `args` | Optional. Harness name to extra CLI arguments. `codex` gets `--sandbox read-only` unless its args name a sandbox. |
| `timeout_seconds` | Optional positive number, default 300. |
| `expect` | At least one of `stdout_contains`, `stdout_not_contains`, `files_unchanged`, `files_changed`, each a list of strings. |

A malformed `eval.json` is reported as an `error` result with the reason.

## Running

```sh
python3 scripts/evals.py                       # every case, every installed harness
python3 scripts/evals.py --case agents-md-delivered --harness claude
python3 scripts/evals.py --list                # case ids and harnesses
python3 scripts/evals.py --require-harness     # a missing harness fails instead of skipping
python3 scripts/evals.py --json                # print results.json
```

`--case` and `--harness` repeat. `--evidence-dir DIR` overrides the evidence location; `--keep` keeps the scratch copies.

Results, one per case and harness:

- `passed`: the harness exited 0 and every expectation held.
- `failed`: an expectation did not hold, or the harness is missing under `--require-harness`.
- `error`: the case is malformed, or the harness could not start, exited non-zero or timed out.
- `skipped`: the harness is not installed. `skipped` is never a pass; it means nothing was tested.

The exit code is 1 when any result is `failed` or `error`, else 0.

## Evidence

Each run writes `.evidence/evals/<UTC run id>/`: `<case>.<harness>.stdout.log`, `<case>.<harness>.stderr.log`, and `results.json` (run id, source commit and dirty flag, and every result). `.evidence/` is ignored by git.

## Initial cases

| Case | Harnesses | A failure means |
|---|---|---|
| `agents-md-delivered` | claude, codex | `AGENTS.md` or the core project skills no longer reach the harness's context. |
| `claude-md-shadows-agents-md` | claude | Tripwire: a `CLAUDE.md` without `@AGENTS.md` no longer hides `AGENTS.md`. Claude Code changed behaviour; update `docs/agent-surfaces.md`. |
| `guard-blocks-root-baseline-edit` | claude | The guard hook let an Edit/Write change the root `intent.md`. |
| `guard-blocks-approval-edit` | claude | The guard hook let an Edit add an approval claim to `change.json`. |
| `worker-brief-stays-in-files` | claude, codex | A worker edited a file outside FILES instead of reporting `BLOCKED`. |

Model output varies between runs. Before changing a case after a failure, rerun it and read the stdout log; never weaken an expectation to make a run pass.

## CI

`.github/workflows/agent-evals.yml` runs the `claude` cases on pull requests that touch agent configuration, weekly, and on demand, when the `ANTHROPIC_API_KEY` repository secret is present (`docs/host-setup.md`, "Optional: credentials for the agent evals"). Without it the job prints a notice and the cases are not run, so a green `evals` job is only meaningful when the secret exists. It is advisory: it is not part of the `repository` gate, because evals spend tokens, need a credential, and depend on a model.
