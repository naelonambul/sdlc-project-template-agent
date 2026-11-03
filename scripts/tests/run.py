#!/usr/bin/env python3
"""Run the control-plane tests in parallel shards, one process per shard.

The runner discovers the same tests `python3 -m unittest discover -s scripts/tests -t .` finds,
splits them by TestCase class, and passes only if every shard passes and every discovered test
was run (or skipped by its class's or module's fixture). `--jobs 1` runs everything in one shard.

This parent process never imports test code. Discovery and each shard run in child processes that
write a result file only after they finish normally, so test code that ends its process early
(SystemExit, os._exit) leaves no result and fails the run instead of passing it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SKIP = re.compile(r"^(setUpClass|setUpModule) \((.+)\)$")


def default_jobs() -> int:
    value = os.environ.get("SDLC_TEST_JOBS")
    return int(value) if value else min(os.cpu_count() or 1, 8)


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("complete") is True else None


# -- child: discovery ------------------------------------------------------------


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def discover_child(out: Path, top: Path, start: str) -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(str(top / start), top_level_dir=str(top))
    errors = list(loader.errors)
    classes: dict[str, dict] = {}
    for test in flatten(suite):
        if isinstance(test, unittest.loader._FailedTest):
            errors.append(f"{test.id()}: {test._exception}")
            continue
        key = f"{type(test).__module__}.{type(test).__qualname__}"
        classes.setdefault(key, {"module": type(test).__module__, "ids": []})["ids"].append(test.id())
    write_json(out, {"classes": classes, "errors": errors, "complete": True})  # only after discovery returned
    return 0


# -- child: one shard -------------------------------------------------------------


class RecordingResult(unittest.TextTestResult):
    """unittest's own result, plus the ids that started and stopped and the fixture-level skips."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.fixture_skips: list[str] = []
        self.test_skips = 0

    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)

    def stopTest(self, test):
        self.stopped.append(test.id())
        super().stopTest(test)

    def addSkip(self, test, reason):
        if isinstance(test, unittest.TestCase):  # a test or a subTest
            self.test_skips += 1
        else:  # a placeholder for a class or module fixture, e.g. "setUpClass (module.Class)"
            self.fixture_skips.append(str(test))
        super().addSkip(test, reason)


def shard_child(out: Path, ids: list[str]) -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in ids)
    result = unittest.TextTestRunner(stream=sys.stderr, resultclass=RecordingResult).run(suite)
    # Written only after run() returned: a SystemExit anywhere in the run, teardowns included, leaves no result.
    write_json(out, {
        "started": result.started,
        "stopped": result.stopped,
        "fixture_skips": result.fixture_skips,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": result.test_skips,
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "successful": result.wasSuccessful(),
        "complete": True,
    })
    return 0 if result.wasSuccessful() else 1


# -- parent ------------------------------------------------------------------------


def plan_shards(classes: dict[str, dict], jobs: int) -> list[list[str]]:
    """Assign whole classes to at most `jobs` shards: largest first, to the least-loaded shard. Deterministic."""
    shards: list[list[str]] = [[] for _ in range(max(1, min(jobs, len(classes))))]
    load = [0] * len(shards)
    for name in sorted(classes, key=lambda n: (-len(classes[n]["ids"]), n)):
        i = load.index(min(load))
        shards[i].append(name)
        load[i] += len(classes[name]["ids"])
    return [sorted(shard) for shard in shards]


def child(args: list[str], top: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), *args], cwd=top, env=env, capture_output=True, text=True)


def verdict(names: list[str], classes: dict[str, dict], proc, result: dict | None) -> tuple[str | None, int, dict]:
    """The first reason a shard fails (or None), how many assigned tests it accounted for, and its counts."""
    counts = {"failures": 0, "errors": 0, "skipped": 0}
    if proc.returncode < 0:
        return f"crashed (signal {-proc.returncode})", 0, counts
    if result is None:
        return f"no result (exit {proc.returncode})", 0, counts
    for key in ("failures", "errors", "skipped"):
        counts[key] = result[key]
    if not result["successful"] or proc.returncode != 0:
        detail = ", ".join(f"{k}={result[k]}" for k in ("failures", "errors", "unexpected_successes"))
        return f"failed (exit {proc.returncode}; {detail})", len(result["started"]), counts

    modules = {classes[name]["module"] for name in names}
    skipped_classes, skipped_modules = set(), set()
    for description in result["fixture_skips"]:
        match = FIXTURE_SKIP.match(description)
        if match and match.group(1) == "setUpClass" and match.group(2) in names:
            skipped_classes.add(match.group(2))
        elif match and match.group(1) == "setUpModule" and match.group(2) in modules:
            skipped_modules.add(match.group(2))
        else:
            return f"unexpected fixture skip: {description}", len(result["started"]), counts
    if Counter(result["started"]) != Counter(result["stopped"]):
        unfinished = sorted((Counter(result["started"]) - Counter(result["stopped"])).elements())
        return f"test did not finish: {', '.join(unfinished) or 'start/stop mismatch'}", len(result["started"]), counts

    covered = [i for n in names if n in skipped_classes or classes[n]["module"] in skipped_modules for i in classes[n]["ids"]]
    expected = Counter(i for n in names if n not in skipped_classes and classes[n]["module"] not in skipped_modules for i in classes[n]["ids"])
    started = Counter(result["started"])
    counts["skipped"] += len(covered)
    accounted = len(result["started"]) + len(covered)
    if started != expected:
        missing, extra = sorted((expected - started).elements()), sorted((started - expected).elements())
        reasons = ([f"tests not run: {', '.join(missing)}"] if missing else []) + ([f"unexpected tests run: {', '.join(extra)}"] if extra else [])
        return "; ".join(reasons), accounted, counts
    return None, accounted, counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=None, help="parallel shards (default: SDLC_TEST_JOBS, else min(cpu count, 8))")
    parser.add_argument("--top", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--start", default="scripts/tests", help=argparse.SUPPRESS)
    parser.add_argument("--discover", type=Path, metavar="FILE", help=argparse.SUPPRESS)
    parser.add_argument("--shard", type=Path, metavar="FILE", help=argparse.SUPPRESS)
    parser.add_argument("ids", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    top = args.top.resolve()

    if args.discover or args.shard:
        sys.path[0] = str(top)  # import test modules as `python -m unittest` from the root would
        return discover_child(args.discover, top, args.start) if args.discover else shard_child(args.shard, args.ids)

    jobs = args.jobs if args.jobs is not None else default_jobs()
    if jobs < 1:
        parser.error("--jobs must be at least 1")
    env = dict(os.environ)
    if sys.warnoptions:
        env["PYTHONWARNINGS"] = ",".join(sys.warnoptions)

    began = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        found = child(["--top", str(top), "--start", args.start, "--discover", str(work / "discovery.json")], top, env)
        discovery = read_json(work / "discovery.json")
        if found.returncode != 0 or discovery is None:
            print((found.stdout + found.stderr).rstrip())
            print(f"FAILED: discovery did not complete (exit {found.returncode})")
            return 1
        if discovery["errors"]:
            for error in discovery["errors"]:
                print(error)
            print(f"FAILED: discovery: {len(discovery['errors'])} error(s)")
            return 1
        classes = discovery["classes"]
        if not classes:
            print("FAILED: discovery: no tests found")
            return 1
        duplicates = sorted(i for i, n in Counter(i for c in classes.values() for i in c["ids"]).items() if n > 1)
        if duplicates:
            print(f"FAILED: discovery: duplicate test id: {', '.join(duplicates)}")
            return 1

        shards = plan_shards(classes, jobs)

        def run_shard(number_names):
            number, names = number_names
            out = work / f"shard-{number}.json"
            began_shard = time.monotonic()
            ids = [i for n in names for i in classes[n]["ids"]]
            proc = child(["--top", str(top), "--shard", str(out), *ids], top, env)
            return proc, read_json(out), time.monotonic() - began_shard

        with ThreadPoolExecutor(max_workers=len(shards)) as pool:
            results = list(pool.map(run_shard, enumerate(shards, 1)))

    total = {"failures": 0, "errors": 0, "skipped": 0}
    accounted_total, problems = 0, []
    for number, (names, (proc, result, seconds)) in enumerate(zip(shards, results), 1):
        assigned = sum(len(classes[name]["ids"]) for name in names)
        problem, accounted, counts = verdict(names, classes, proc, result)
        for key in total:
            total[key] += counts[key]
        accounted_total += accounted
        print(f"shard {number}: {assigned} tests, {'ok' if problem is None else 'FAILED'} in {seconds:.1f}s: {' '.join(names)}")
        if problem:
            problems.append(f"shard {number} {problem}")
            print((proc.stdout + proc.stderr).rstrip())

    plural = "shard" if len(shards) == 1 else "shards"
    detail = ", ".join(f"{k}={v}" for k, v in total.items())
    line = f"ran {accounted_total} tests in {len(shards)} {plural} ({detail}) in {time.monotonic() - began:.1f}s"
    if problems:
        print(f"FAILED: {line}; {'; '.join(problems)}")
        return 1
    print(f"OK: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
