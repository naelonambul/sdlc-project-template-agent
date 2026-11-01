# Implementation Plan

## Summary

Make `repo.py status` fast without changing any result it reports. Today it starts one `git` process per object or listing, so its cost grows with every frozen packet. This change reads git objects through one long-lived `git cat-file --batch` process and replaces three per-packet commands with one command each.

This is a `repository` change to `scripts/repo.py` and its tests. It changes no `status --json` output, exit code, reason code, closure rule, anchor rule, `checks.json`, `.github/**`, or dependency. `repo.py` stays standard-library Python that needs only Git.

### Measurements

Taken on 2026-11-01 on an Apple M4 with Git 2.54.0 and Python 3.13.13, at `1bb1ff6`:

- `status` took about 2.95s and made 331 `git` calls, about 8.7ms each. Almost all of the runtime was spent waiting on `git`; 32 packets accounted for 2.84s.
- A scratch prototype gave these cumulative times:

| Step | 32 packets | 332 synthetic packets |
|---|---|---|
| Original | 2.95s | 33-36s |
| One `cat-file --batch` process | 1.04s | 13-15s |
| One `ls-files` | 0.77s | not measured |
| One `git log` for closure commits | 0.47s | not measured |
| Tree objects read through the batch process | 0.18s | 0.32-0.44s |

### Rejected options

- **Rewriting `repo.py` in Rust.** Shelling out keeps the same process spawns. `libgit2` avoids them, but it breaks "Python 3 and Git only" and reimplements the integrity logic. This was reasoned, not benchmarked.
- **Finding anchors from `git log --raw` and status `A`.** In the differential fuzz below, that version disagreed with the current code in 636 of 1,000 comparisons. Renames and copies, gitlinks, `log.showRoot`, and a closure deleted at the tip all separate `A` from the anchor rule.
- **A persistent on-disk cache of verified packets.** It would turn a recomputed integrity check into a trusted record.
- **Running `repo.main()` in-process in tests, or a faster test fixture.** Those are test-speed work and are out of scope. A later change may add a parallel test runner, which measured 66s to about 18s.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/repo.py`:
  - New class `Objects`: owns one `git cat-file --batch` process. `read(spec)` returns `(type, bytes)` or `None` when the object is missing. `blob(spec)` returns bytes only when the object is a blob, because the current `git cat-file blob` fails on a tree or commit. `close()` closes both pipes and waits for the process.
  - `Context`: lazily creates `objects`, and gains `packet_paths(change_id)`, `closure_commits`, and `close()`.
  - `tree_file`, `tree_packet`, and `find_closure_anchor` take `ctx` and read through `ctx.objects`.
  - `worktree_packet(root, change_id, listing=None)`: an optional precomputed listing. Callers that pass none, including `close`, `verify` and the candidate check, keep listing fresh.
  - `compute_status`: closes the context in a `finally` around the `evaluate_change` loop.
- `scripts/tests/test_status.py`: new class `BatchedReads`, and the one existing `repo.tree_packet` call updated to the new signature.

### Design

The anchor rule stays one predicate, unchanged in meaning. Batching only supplies candidate commits, so a wrong candidate cannot pass as an anchor:

```python
@property
def closure_commits(self) -> dict:
    """closure.json path -> first-parent commits that touch it, newest first."""
    if self._closure_commits is None:
        log = git(self.root, "log", "--first-parent", "-m", "--root", "--no-renames", "--name-only", "--format=%x00%H",
                  self.baseline_ref, "--", f":(glob){CHANGES}/*/{CLOSURE}")
        self._closure_commits = {}
        for record in filter(None, log.split("\0")):
            commit, *paths = record.split()
            for path in set(paths):
                self._closure_commits.setdefault(path, []).append(commit)
    return self._closure_commits


def find_closure_anchor(ctx: Context, change_id: str) -> str | None:
    """Newest first-parent commit that introduces the closure.json on the baseline branch's tip."""
    path = f"{CHANGES}/{change_id}/{CLOSURE}"
    if tree_file(ctx, ctx.baseline_ref, path) is None:
        return None
    for commit in ctx.closure_commits.get(path, []):
        if tree_file(ctx, commit, path) is not None and tree_file(ctx, f"{commit}^1", path) is None:
            return commit
    return None
```

A root commit has no `^1`, so `tree_file` returns `None`, which matches the current `not parent` branch.

`tree_packet` walks tree objects from `<commit>:changes/<id>` through `ctx.objects`:

- Each entry is `<mode> <name>\0<raw oid>`. The oid length is half the length of the hex commit id, so SHA-256 repositories work.
- Mode `40000` is a subtree, mode `160000` is a gitlink and is skipped, as `ls-tree` lists it as a commit today, and every other mode is a blob.
- A missing packet returns `{}`.
- A blob or tree that a parent tree names but the object store cannot supply raises `GitError`, as the current `git cat-file blob <oid>` does.
- Names decode as strict UTF-8, as `git()` does today, so a non-UTF-8 name fails the same way.

`packet_paths` runs `git ls-files -co --exclude-standard -z -- changes/` once and groups paths by `path.split("/")[1]`, keeping only paths with more than two components. Only `check_anchored_closure` uses it. It is valid because `status` never writes to the worktree, and the cache lives only as long as one `Context`.

## Order of work

Each step is one commit and one coordinator edit, so the route is single agent. Each proves itself with the same command: `python3 -m unittest scripts.tests.test_status`.

1. Add `BatchedReads` against the current code. Every test must pass before any implementation change, which proves it pins today's behaviour.
2. Add `Objects` and the context lifecycle, and move `tree_file` and the blob reads in `tree_packet` onto them.
3. Add `packet_paths` and the `worktree_packet` listing argument.
4. Add `closure_commits` and the new `find_closure_anchor`.
5. Replace the `ls-tree` call in `tree_packet` with the tree walk.
6. Compare before and after, as Tests and proof describes.
7. Run `python3 scripts/repo.py verify --change status-batching --full`, then close per `changes/README.md`.

## Tests and proof

`BatchedReads` builds real repositories through `RepoCase` and asserts the status result. Existing tests already cover a squash anchor, a merge-commit anchor, and a reused id, so these cases are added only where they are missing:

- A newer-dated side-branch commit that adds the closure, merged into a main line that already had it. The anchor stays on the first-parent chain. This case is required: dropping `--first-parent` from the prototype survived the fuzz.
- A closure added by a rename or an identical copy from another packet.
- A closure deleted at the tip, with no anchor reported.
- Delete and re-add, anchoring at the re-add.
- A gitlink at `closure.json`, a gitlink inside a closed packet, a symlink `closure.json`, and a directory at `closure.json`.
- Nested and non-ASCII file names inside a frozen packet.
- A non-UTF-8 file name in a frozen packet fails as it does today.
- Each of the above under a hostile global config: `log.showRoot=false`, `log.diffMerges=separate`, `diff.renames=copies`, `diff.ignoreSubmodules=all`.
- The object process exits when `status` finishes, with no `ResourceWarning`.

Then:

- **Identical output.** `status --json` from the old and new `repo.py` is byte-identical on this repository.
- **Differential check.** Compare `status --json`, exit code, and `find_closure_anchor` between `1bb1ff6` and the implementation on 500 random repositories, half of them under the hostile config. Each history mixes true merges, renames, copies, deletes and re-adds, gitlinks, symlinks, valid closures, and worktree tampering. The result must show no differences and no harness errors, and include frozen closures. This is one-off evidence for the pull request, not a registered check.
- **Sensitivity.** Temporarily remove `--first-parent`, then `--root`, then the parent check, then the blob type check. Each removal must fail at least one test.
- **Speedup.** `status` on this repository takes under 0.3s and makes fewer than 20 `git` process starts.
- `python3 scripts/repo.py verify --change status-batching --full` reports no `failed`, `blocked`, or `not-run` check.

No `AGENTS.md`, skill, or guard file changes, so no smoke probe is required.

## Risks and mitigations

- **Riskiest step: step 4, the anchor rule.** It decides which commit a frozen packet is checked against. The predicate stays the only judge, and the tests in step 1 exist before it changes.
- **First-parent order is not caught by fuzzing.** The required side-branch test covers it. It must fail when `--first-parent` is removed.
- **Older Git.** `-m` was chosen over `--diff-merges`, which needs Git 2.31, but only Git 2.54 and the CI runner's Git were exercised.
- **Corrupted repositories** were not fuzzed. Missing objects raise `GitError` by design.
- **A line-based batch protocol.** A newline in a spec would desynchronize it. Specs are built from commit ids and paths with validated change ids, and `evaluate_change` rejects invalid ids before any read.
- **Timings are from one machine.** CI timing is not a success criterion.

## Rollback or recovery

Before merge, drop the branch. After merge, open a new change that restores `scripts/repo.py` and `scripts/tests/test_status.py`. No data, packet, or closure format changes, so nothing needs migrating.

## Open questions

None.
