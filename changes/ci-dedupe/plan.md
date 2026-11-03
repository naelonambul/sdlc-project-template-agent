# Implementation Plan

## Summary

The CI job `control-plane-tests` runs the whole control-plane suite sequentially (`python3 -m unittest discover -s scripts/tests -t . -v`, about 42s locally plus setup). `verify-core` runs the same suite again through `repo.py verify`, which since `parallel-tests` uses the shard runner. The jobs run in parallel, and locally the sequential suite is by far the slowest of them, so it is expected to set the wall time of a CI run. That expectation is not measured on CI (see Tests and proof).

This change:
- points `control-plane-tests` at the shard runner, `python3 scripts/tests/run.py`;
- runs the runner's own tests outside the runner first, in the same job;
- adds a strict workflow invariant that keeps the job's commands fixed and its failures effective.

The job is kept, not removed, because it is the only run of the tests whose result does not depend on `repo.py verify`'s routing and pass/fail judgment.

This change edits `.github/workflows/repository.yml`, which the agent identity cannot push. It follows "Workflow changes" in `docs/host-setup.md`: the owner pushes the workflow commit once, and the agent pushes the closure and opens the pull request. This is the first real use of that documented handoff.

## Revision 2

Before implementation, the approved first draft was reviewed read-only by Codex (`gpt-6-astra`, "approve with changes") and Antigravity (`gemini-4-argon-high`, "approve"). This revision adopts their findings, each checked against the code:

- The planned invariant (the job's steps *contain* the registered command and do not mention `repo.py`) would still pass with `|| true`, `echo …`, a step-level `if: false` or `continue-on-error: true`. It now compares the job's run commands exactly and forbids those keys.
- If `run.py` exited 0 before running anything, both test jobs would pass, and the runner's own tests and count check would never run. The job now runs `python3 -m unittest scripts.tests.test_run` before the runner.
- Statements corrected:
  - the independence claim is narrowed to `repo.py verify`'s routing and judgment;
  - the "every pull request" claim is dropped, because `verify-core` also selects `control-plane` on every valid pull request today (`changes/**` is in its paths);
  - the log limit belongs to the `agent-gh` wrapper, not to the App;
  - the 4 vCPU figure holds for public repositories, which this one is.
- The handoff steps now name the exact refs and the remote check.

## Decision: keep the job, change its command

- **Chosen: keep `control-plane-tests` and run the shard runner in it.**
  - The job's result does not depend on `repo.py verify`. `verify-core` runs the tests through `repo.py verify`, and a pull request can change `repo.py`. If such a change made `verify` route a check away or report `passed` without running it, this job would still run the tests and fail.
  - The independence is limited. The tests import `repo.py` as the code under test, and the runner passes its environment to the shards. What the job adds is a pass/fail decision that `repo.py` does not make.
  - The runner keeps that property. It is a standard-library script in `scripts/tests/` that does not import `repo.py`, and it fails unless the shards ran every discovered test. Running `test_run` with plain `unittest` first means a runner that silently does nothing still fails the job.
- **Rejected: remove `control-plane-tests` as a duplicate of `verify-core`.** It would save one runner's minutes, but `repo.py` would then certify its own changes, which the template's layered enforcement does not accept (AGENTS.md, Authority 2).
- **Rejected: drop `control-plane` from `verify-core` instead.** `close` requires a complete `verify --full`, so the control-plane tests would disappear from local evidence, and the template's only `core` check would be gone.
- **Rejected: run the job only on some events or paths.** The workflow forbids path filters and job-level `if:` (`test_workflow.py`), and `summary` fails on a skipped job.
- **Rejected: keep `-v` sequential output.** The runner prints each shard's classes, prints a failed shard's full output, and ends with a one-line summary. Per-test `-v` lines add nothing a failure does not already show.

## Files and components that change

- `.github/workflows/repository.yml`, job `control-plane-tests`: the single step `run: python3 -m unittest discover -s scripts/tests -t . -v` becomes two steps, in this order:
  - `run: python3 -m unittest scripts.tests.test_run`
  - `run: python3 scripts/tests/run.py`

  Nothing else in the workflow changes: no other job, trigger, permission, action pin, timeout or `needs` entry.
- `scripts/tests/test_workflow.py`: add `test_control_plane_job_runs_the_registered_command_without_repo_py`. It reads the `control-plane-tests` job block, with `#` comments removed, and asserts:
  - the job's `run:` values, in order, equal exactly `["python3 -m unittest scripts.tests.test_run", " ".join(control-plane argv from checks.json)]`;
  - the job block contains no step-level `if:`, no `continue-on-error:` and no `working-directory:`;
  - no `run:` value in the job contains `repo.py`.

## Order of work

1. `scripts/tests/test_workflow.py`: the new invariant, as its own commit. Proof: `python3 -m unittest scripts.tests.test_workflow` fails, because the job still runs `unittest discover -v`.
2. `.github/workflows/repository.yml`: the two-step change, as its own commit, after step 1's commit and last among the implementation commits, as the handoff requires. Proof: `python3 scripts/tests/run.py` passes, including the new invariant.
3. `python3 scripts/repo.py status --change ci-dedupe`, then `python3 scripts/repo.py verify --change ci-dedupe --full`, then `python3 scripts/repo.py close ci-dedupe --evidence <path>`, then commit the closure on top. Nothing that contains the workflow commit is pushed by the agent.
4. Handoff (`docs/host-setup.md`, "Workflow changes"):
   - the agent gives the owner the workflow commit's full SHA and stops;
   - the owner runs `git push origin <sha>:refs/heads/change/ci-dedupe`, and nothing further;
   - the agent checks `git ls-remote origin refs/heads/change/ci-dedupe` and confirms it equals that SHA;
   - the agent runs `agent-gh push origin change/ci-dedupe:refs/heads/change/ci-dedupe`, which pushes the closure commit, and opens the pull request with `Change-ID: ci-dedupe`.
5. After CI: confirm the pull request's final head is the agent's closure commit, the pull request author is the agent identity, and the `repository` run on that head is `success` (`docs/host-setup.md`'s checks for the handoff). Any later fix that is not to the workflow goes in a new commit, followed by `verify --full`, `close`, a closure commit and an agent push. A fix to the workflow repeats the handoff.

## Tests and proof

- **Invariant sensitivity:** the new test fails on the current workflow (step 1). In an in-memory copy of the workflow text it also fails for each of:
  - `python3 scripts/tests/run.py || true`;
  - `echo python3 scripts/tests/run.py`;
  - the `test_run` step removed;
  - a step-level `if: false`;
  - `continue-on-error: true`;
  - a run step calling `python3 scripts/repo.py verify`;
  - a `checks.json` argv that no longer matches the job.

  These cases are asserted inside the test itself, so the sensitivity stays checked.
- **Local:** `python3 scripts/tests/run.py` and `python3 -m unittest discover -s scripts/tests -t .` pass with the same test count, and `python3 -m unittest scripts.tests.test_run` passes.
- `python3 scripts/repo.py status --change ci-dedupe` and `python3 scripts/repo.py verify --change ci-dedupe --full` pass.
- **CI:** the pull request's `repository` run on the final head is `success`, with `summary` requiring `control-plane-tests`, `status`, `verify-core` and `identity`, as before.
  - The host's `agent-gh` wrapper allows `run list` and `pr checks` but not job logs or durations. The owner can read the `control-plane-tests` duration in the Actions UI. It is reported if the owner supplies it, and it is not a gate.
- After merge, the `push` run on `main` is `success`.

## Risks and mitigations

- **Riskiest step: the handoff.** If the agent pushes anything containing the workflow commit, the push is refused. If the owner pushes past it, the owner becomes the last pusher and cannot approve. Mitigations:
  - follow the table in `docs/host-setup.md` exactly;
  - give the owner the exact command with the full SHA;
  - confirm the remote head with `ls-remote` before the agent's push;
  - if the owner pushed the closure commit too, the agent pushes one more commit to become the last pusher again (`docs/host-setup.md`).
- **`main` moves during the handoff.** The App cannot rebase the workflow commit. Mitigation: the owner may use **Update branch** on the pull request; then the agent reruns `verify --full` and `close`, commits the closure and pushes once more.
- **Fewer cores on CI.** `ubuntu-latest` has 4 vCPUs for public repositories, so the runner uses 4 shards. Measured locally: `--jobs 4` takes 15–16s, against 42s sequentially.
- **A runner bug now affects both test jobs.** Mitigations:
  - `test_run` runs under plain `unittest` first;
  - the runner's count check;
  - `python3 -m unittest discover` stays documented as the sequential equivalent in `scripts/README.md`.

  Not covered: a future edit that makes `run.py` import `repo.py`. Such an edit goes through review like any other change to `scripts/tests/`.
- **Later fixes to the workflow** need the handoff again. Fixes to anything else go in new commits on top.

## Rollback or recovery

Open a new change that sets the `control-plane-tests` steps back to `python3 -m unittest discover -s scripts/tests -t . -v` and drops the new invariant. That change needs the same owner handoff.

## Open questions

None.
