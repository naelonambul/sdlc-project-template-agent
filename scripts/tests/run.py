#!/usr/bin/env python3
"""Run the control-plane tests in parallel shards, one `python -m unittest` process per shard.

The runner discovers the same tests `python3 -m unittest discover -s scripts/tests -t .` finds,
splits them by TestCase class, and passes only if every shard passes and the shards together ran
exactly the discovered tests. `--jobs 1` runs everything in one process.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAN = re.compile(r"(?m)^Ran (\d+) tests? in ")
COUNTS = re.compile(r"(?m)^(?:OK|FAILED) \((.*)\)$")


def default_jobs() -> int:
    value = os.environ.get("SDLC_TEST_JOBS")
    return int(value) if value else min(os.cpu_count() or 1, 8)


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def discover(top: Path, start: str) -> tuple[dict[str, int], list[str]]:
    """Discovered test count per `module.Class`, and discovery errors."""
    loader = unittest.TestLoader()
    suite = loader.discover(str(top / start), top_level_dir=str(top))
    errors = list(loader.errors)
    classes: dict[str, int] = {}
    for test in flatten(suite):
        if isinstance(test, unittest.loader._FailedTest):
            errors.append(f"{test.id()}: {test._exception}")
            continue
        key = f"{type(test).__module__}.{type(test).__qualname__}"
        classes[key] = classes.get(key, 0) + 1
    return classes, errors


def plan_shards(classes: dict[str, int], jobs: int) -> list[list[str]]:
    """Assign whole classes to at most `jobs` shards: largest first, to the least-loaded shard. Deterministic."""
    shards: list[list[str]] = [[] for _ in range(max(1, min(jobs, len(classes))))]
    load = [0] * len(shards)
    for name in sorted(classes, key=lambda n: (-classes[n], n)):
        i = load.index(min(load))
        shards[i].append(name)
        load[i] += classes[name]
    return [sorted(shard) for shard in shards]


def run_shard(names: list[str], top: Path, env: dict) -> tuple[subprocess.CompletedProcess, float]:
    began = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", *names],
        cwd=top,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, time.monotonic() - began


def parse(output: str) -> tuple[int | None, dict[str, int]]:
    ran = RAN.findall(output)
    counts: dict[str, int] = {}
    match = COUNTS.search(output)
    if match:
        for part in match.group(1).split(","):
            key, _, value = part.strip().partition("=")
            counts[key] = int(value)
    return (int(ran[-1]) if ran else None), counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=None, help="parallel shards (default: SDLC_TEST_JOBS, else min(cpu count, 8))")
    parser.add_argument("--top", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--start", default="scripts/tests", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    jobs = args.jobs if args.jobs is not None else default_jobs()
    if jobs < 1:
        parser.error("--jobs must be at least 1")
    top = args.top.resolve()

    began = time.monotonic()
    classes, errors = discover(top, args.start)
    if errors:
        for error in errors:
            print(error)
        print(f"FAILED: discovery: {len(errors)} error(s)")
        return 1
    if not classes:
        print("FAILED: discovery: no tests found")
        return 1

    env = dict(os.environ)
    if sys.warnoptions:
        env["PYTHONWARNINGS"] = ",".join(sys.warnoptions)
    shards = plan_shards(classes, jobs)
    with ThreadPoolExecutor(max_workers=len(shards)) as pool:
        results = list(pool.map(lambda names: run_shard(names, top, env), shards))

    total = {"failures": 0, "errors": 0, "skipped": 0}
    ran_total, problems = 0, []
    for number, (names, (proc, seconds)) in enumerate(zip(shards, results), 1):
        expected = sum(classes[name] for name in names)
        ran, counts = parse(proc.stdout)
        for key in total:
            total[key] += counts.get(key, 0)
        ran_total += ran or 0
        if proc.returncode < 0:
            problem = f"shard {number} crashed (signal {-proc.returncode})"
        elif ran is None:
            problem = f"shard {number} printed no test summary (exit {proc.returncode})"
        elif ran != expected:
            problem = f"shard {number} count mismatch: ran {ran}, discovered {expected}"
        elif proc.returncode != 0:
            problem = f"shard {number} failed (exit {proc.returncode})"
        else:
            problem = None
        status = "ok" if problem is None else "FAILED"
        print(f"shard {number}: {expected} tests, {status} in {seconds:.1f}s: {' '.join(names)}")
        if problem:
            problems.append(problem)
            print(proc.stdout.rstrip())

    discovered = sum(classes.values())
    if ran_total != discovered and not problems:
        problems.append(f"count mismatch: ran {ran_total}, discovered {discovered}")
    plural = "shard" if len(shards) == 1 else "shards"
    detail = ", ".join(f"{k}={v}" for k, v in total.items())
    line = f"ran {ran_total} tests in {len(shards)} {plural} ({detail}) in {time.monotonic() - began:.1f}s"
    if problems:
        print(f"FAILED: {line}; {'; '.join(problems)}")
        return 1
    print(f"OK: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
