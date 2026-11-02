# Implementation Plan

## Summary

The CI job `control-plane-tests` runs the whole control-plane suite sequentially (`python3 -m unittest discover -s scripts/tests -t . -v`, about 42s locally plus setup). `verify-core` runs the same suite again through `repo.py verify`, which since `parallel-tests` uses the shard runner. The jobs run in parallel, so the sequential job sets the wall time of every CI run.

This change points `control-plane-tests` at the shard runner, `python3 scripts/tests/run.py`, and adds a workflow invariant that keeps the job and the registered `control-plane` check on the same command. The job is kept, not removed, because it is the only run of the tests that does not go through `repo.py`.

This change edits `.github/workflows/repository.yml`, which the agent identity cannot push. It follows "Workflow changes" in `docs/host-setup.md`: the owner pushes the workflow commit once, and the agent pushes the closure and opens the pull request.

## Decision: keep the job, change its command

- **Chosen: keep `control-plane-tests` and run the shard runner in it.**
  - The job is the one test run that a broken `repo.py` cannot certify. `verify-core` runs the tests through `repo.py verify`, and a pull request can change `repo.py`. If such a change made `verify` report `passed` without running a check, only this job would still fail.
  - The job also runs the tests on every pull request whatever the routing decides.
  - The runner keeps that independence. It is a plain script in `scripts/tests/`, it does not import `repo.py`, and it fails unless the shards ran every discovered test.
- **Rejected: remove `control-plane-tests` as a duplicate of `verify-core`.** That would save one runner's minutes, but it would leave `repo.py` certifying its own changes, which the template's enforcement model does not accept (AGENTS.md: hard rules are enforced by `scripts/repo.py`, tests, and CI).
- **Rejected: keep `-v` sequential output.** The runner prints each shard's classes, prints a failed shard's full output, and ends with a one-line summary. Per-test `-v` lines add nothing a failure does not already show.

## Files and components that change

- `.github/workflows/repository.yml`, job `control-plane-tests`: the step `run: python3 -m unittest discover -s scripts/tests -t . -v` becomes `run: python3 scripts/tests/run.py`. Nothing else in the workflow changes: no job, trigger, permission, action pin, timeout or `needs` entry.
- `scripts/tests/test_workflow.py`: add `test_control_plane_job_runs_the_registered_command_without_repo_py`:
  - the `control-plane-tests` job's run steps contain the registered `control-plane` argv from `checks.json`, joined with spaces;
  - no run step in that job invokes `repo.py`.

## Order of work

1. `scripts/tests/test_workflow.py`: the new invariant. Proof: `python3 -m unittest scripts.tests.test_workflow` fails, because the job still runs `unittest discover -v`.
2. `.github/workflows/repository.yml`, the one-line change, committed as its own commit, last among the implementation commits, as the handoff requires. Proof: `python3 scripts/tests/run.py` passes, including the new invariant.
3. `python3 scripts/repo.py status --change ci-dedupe`, then `python3 scripts/repo.py verify --change ci-dedupe --full`, then `close`, with the closure committed on top. Nothing that contains the workflow commit is pushed.
4. Handoff (`docs/host-setup.md`, "Workflow changes"):
   - the agent gives the owner the workflow commit's SHA and stops;
   - the owner runs `git push origin <sha>:refs/heads/change/ci-dedupe`;
   - the agent confirms on the remote that the branch head is that SHA, then pushes the closure commit and opens the pull request.

## Tests and proof

- **Invariant sensitivity:** the new test fails on the current workflow (step 1). In a scratch copy it also fails for:
  - a job that runs `python3 scripts/repo.py verify` instead;
  - a `checks.json` argv that no longer matches the job.
- **Local:** `python3 scripts/tests/run.py` and `python3 -m unittest discover -s scripts/tests -t .` pass with the same test count.
- `python3 scripts/repo.py status --change ci-dedupe` and `python3 scripts/repo.py verify --change ci-dedupe --full` pass.
- **CI:** the pull request's `repository` run is `success`, with `summary` requiring `control-plane-tests`, `status`, `verify-core` and `identity`, as before.
  - The agent identity can read only `run list`, not job logs or durations. The owner can read the `control-plane-tests` duration in the Actions UI. It is reported if the owner supplies it, and it is not a gate.

## Risks and mitigations

- **Riskiest step: the handoff.** If the agent pushes anything containing the workflow commit, the push is refused. If the owner pushes past it, the owner becomes the last pusher and cannot approve. Mitigation: follow the table in `docs/host-setup.md` exactly, and confirm the remote head SHA before the agent's push.
- **Fewer cores on CI.** `ubuntu-latest` has 4 vCPUs, so the runner uses 4 shards. Measured locally: `--jobs 4` takes 15–16s, against 42s sequentially.
- **A runner bug would now affect both jobs.** Mitigation: `parallel-tests`'s runner tests and count check. `python3 -m unittest discover` stays documented as the sequential equivalent in `scripts/README.md`.
- **Later fixes to the workflow** need the handoff again. Fixes to anything else go in new commits on top.

## Rollback or recovery

Open a new change that sets the `control-plane-tests` step back to `python3 -m unittest discover -s scripts/tests -t . -v` and drops the new invariant. That change needs the same owner handoff.

## Open questions

None.
