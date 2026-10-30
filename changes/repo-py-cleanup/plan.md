# Implementation Plan

## Summary

`scripts/repo.py` repeats several small patterns, keeps two unused names, and has three long functions that mix separate concerns. This change removes the repetition and splits those functions. It changes no behavior: no command, flag, message, exit code or JSON field differs. The file stays a single, stdlib-only script, because copying one file is how it is meant to travel.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

Only `scripts/repo.py`. No test file changes, because the unchanged tests are the proof.

Shared helpers:

- `repo_root()` replaces the four `Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())` expressions.
- `baseline_branch(root)` replaces the three `load_config(root).get("baseline_branch", "main")` expressions.
- `git_paths(root, *args)` replaces the six `filter(None, ... .split("\0"))` expressions that read NUL-separated git output. `tree_packet` keeps its own parsing if its entries are not plain paths.
- `check_change_id(cid)` replaces the identical checks in `approval_claim` and `closure_record`. `new_packet_files` keeps its own check, because its message differs.
- `changed_paths` merges its two branches around one `git diff` call.

Command handling:

- `main` catches `Refusal` once and prints `refused: <message>` with exit 1, replacing the three `except Refusal` blocks. `cmd_new` keeps its `OSError` handling.
- `build_parser` sets `func` on each subcommand, and `main` calls `args.func(args)` in place of the `if` chain.

Dead code:

- Remove `CHECK_STATUSES`, which nothing reads. `log_digest` stays: it looks like a redundant wrapper, but `test_missing_evidence_after_success_is_blocked` patches it to simulate a lost log.

Function splits, moving code without changing it:

- `evaluate_change`: the approval loop moves to `check_approvals`, which returns `approved_at`, `stale_approval` and `unbound_scope`, and the ordering block moves to `check_order`.
- `check_closure`: the anchored and candidate paths move to `check_anchored_closure` and `check_candidate_closure`.
- `surface_findings`: instruction checks move to `instruction_findings` and adapter checks to `adapter_findings`. `surface_findings` joins them with `hook_findings`.

## Order of work

1. Capture the baseline from main in a scratch directory: `status --json`, `status`, and `verify --dry-run --json` with `run_id` removed, each with its exit code, plus the refusal output of `new`, `approve` and `close` with an invalid id. Proof: the files exist and are not empty.
2. Add the helpers and remove the dead code. Proof: `python3 -m unittest discover -s scripts/tests -t .` passes.
3. Change command handling. Proof: the same test command passes.
4. Split the three functions, one commit-sized step at a time. Proof: the same test command passes after each.
5. Compare with the baseline. Proof: `diff` of each capture from step 1 is empty, apart from the active packet this change adds, which the comparison run excludes by running from a clone of the candidate with the packet removed.
6. `git diff --exit-code main -- scripts/tests`, `python3 scripts/repo.py status --change repo-py-cleanup` and `python3 scripts/repo.py verify --change repo-py-cleanup --full` pass, then close per `changes/README.md`.

## Tests and proof

- All 151 existing tests pass with no test file changed.
- The before-and-after captures of step 1 and step 5 are byte-identical.
- The change aims at fewer repeated patterns and shorter functions, not fewer lines. `scripts/repo.py` grows by 16 lines, from 1,403 to 1,419, because each split adds a signature and surrounding blank lines.
- `evaluate_change` is under 60 lines, and `check_closure` and `surface_findings` are under 25 each.

## Risks and rollback

- **Riskiest step: moving `Refusal` handling to `main`.** Every `raise Refusal` is reached only from `new`, `approve` or `close`, which already catch it, so `status` and `verify` gain no new path. The refusal captures pin the messages and exit codes.
- **`check_approvals` shares state with later steps.** It returns the values `evaluate_change` needs, and `st.add` order stays the same because the code runs in the same sequence, so `reasons` order in `--json` is unchanged. The captures pin this for the repository's packets, and the tests for the error cases.
- **Merge conflicts** with other open changes to `repo.py`. None is open.
- Rollback: revert the squash commit.

## Out of scope

- Reducing git calls, including `git cat-file --batch`.
- Changes to `guard.py`, tests, CI, or documentation.
- Splitting `repo.py` into several files, or sharing code with `guard.py`.
- Any change to messages or to the `new` id check.
