#!/usr/bin/env python3
"""agent-task-runner: a tiny, idempotent task runner for local agents.

Pattern sources (patterns only, original code):
  - vercel-labs/agent-browser: one small, focused CLI tool built for
    agents, not a framework. This runner is likewise one file, one job:
    run a list of commands reliably.
  - microsoft/ai-agents-for-beginners: learn by building the loop
    itself -- read a task list, execute, observe, retry, report.
  - addyosmani/agent-skills: reusable, composable units. Here each
    task is a self-contained unit with its own retries and timeout.

Design rules (deliberate, and the reason this stays safe to hand to
an agent):
  1. Commands are argv lists, NEVER shell strings. There is no
     shell=True anywhere, so `; rm -rf /` is a literal argument that
     fails, not a second command that runs.
  2. No network, no keys, no dependencies beyond the Python standard
     library. The runner never reads .env.
  3. Idempotent reruns: with --skip-succeeded, a task that already
     succeeded for the exact same argv is skipped on the next run.
     State lives in a plain JSON file you can read and delete.
  4. Every attempt is logged as one JSON line, so a later agent (or
     human) can audit exactly what ran, for how long, and why it
     failed -- without re-running anything.

Task file format (JSON list), see tasks.example.json:
  {"id": "backup", "argv": ["python3", "-c", "print('ok')"],
   "retries": 2, "timeout": 30, "cwd": null}

Usage:
  python3 agent_task_runner.py --tasks tasks.json
  python3 agent_task_runner.py --tasks tasks.json --skip-succeeded
  python3 agent_task_runner.py --tasks tasks.json --dry-run
  python3 agent_task_runner.py --demo
  python3 agent_task_runner.py --tasks tasks.json --report report.md

Exit code: 0 when every executed task succeeded (or was skipped),
1 when any task failed, 2 on bad input.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

MAX_OUTPUT_CHARS = 4000


def task_hash(task):
    """Stable fingerprint of a task's identity: argv only."""
    blob = json.dumps(task.get("argv", []), sort_keys=True,
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_tasks(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("task file must contain a JSON list")
    for task in data:
        if not isinstance(task, dict) or not task.get("id"):
            raise ValueError("each task needs an 'id'")
        argv = task.get("argv")
        if (not isinstance(argv, list) or not argv
                or not all(isinstance(a, str) for a in argv)):
            raise ValueError(
                f"task {task.get('id')!r}: 'argv' must be a non-empty "
                "list of strings (shell strings are rejected)")
        if task.get("retries", 0) < 0 or task.get("timeout", 0) < 0:
            raise ValueError(f"task {task['id']!r}: negative retries/timeout")
    return data


def load_state(path):
    if path and Path(path).exists():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}
    return {}


def run_one(task, log_fh):
    """Run one task with retries. Returns a result dict."""
    retries = int(task.get("retries", 0))
    timeout = task.get("timeout") or None
    attempts = 0
    started = time.time()
    last = None
    for attempt in range(retries + 1):
        attempts += 1
        t0 = time.time()
        try:
            proc = subprocess.run(
                task["argv"], capture_output=True, text=True,
                timeout=timeout, cwd=task.get("cwd") or None)
            last = {"exit_code": proc.returncode,
                    "stdout": proc.stdout[:MAX_OUTPUT_CHARS],
                    "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
                    "timed_out": False}
        except subprocess.TimeoutExpired as exc:
            last = {"exit_code": None,
                    "stdout": (exc.stdout or b"").decode("utf-8", "replace")[:MAX_OUTPUT_CHARS]
                    if isinstance(exc.stdout, bytes) else (exc.stdout or "")[:MAX_OUTPUT_CHARS],
                    "stderr": "",
                    "timed_out": True}
        except FileNotFoundError:
            last = {"exit_code": None, "stdout": "",
                    "stderr": f"command not found: {task['argv'][0]}",
                    "timed_out": False}
        except OSError as exc:
            last = {"exit_code": None, "stdout": "",
                    "stderr": str(exc), "timed_out": False}
        record = {"task": task["id"], "attempt": attempt + 1,
                  "duration_s": round(time.time() - t0, 3), **last}
        if log_fh:
            log_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            log_fh.flush()
        if last["exit_code"] == 0:
            break
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    result = {"id": task["id"], "hash": task_hash(task),
              "status": "ok" if last and last["exit_code"] == 0 else "failed",
              "attempts": attempts,
              "duration_s": round(time.time() - started, 3),
              "exit_code": last["exit_code"] if last else None,
              "timed_out": bool(last and last["timed_out"])}
    return result


def run_all(tasks, state, skip_succeeded, log_path):
    """Run every task; returns results, mutating state in place."""
    results = []
    log_fh = open(log_path, "a", encoding="utf-8") if log_path else None
    try:
        for task in tasks:
            if skip_succeeded and state.get(task["id"], {}).get("hash") == task_hash(task) \
                    and state[task["id"]].get("status") == "ok":
                results.append({"id": task["id"], "hash": task_hash(task),
                                "status": "skipped", "attempts": 0,
                                "duration_s": 0.0, "exit_code": 0,
                                "timed_out": False})
                continue
            result = run_one(task, log_fh)
            results.append(result)
            state[task["id"]] = {"hash": result["hash"],
                                 "status": result["status"]}
    finally:
        if log_fh:
            log_fh.close()
    return results


def render_markdown(results):
    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    lines = [f"# Run report: {ok} ok, {skipped} skipped, {failed} failed",
             "", "| task | status | attempts | seconds |",
             "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['status']} | {r['attempts']} | "
                     f"{r['duration_s']} |")
    return "\n".join(lines) + "\n"


DEMO_TASKS = [
    {"id": "hello", "argv": [sys.executable, "-c", "print('hello from runner')"],
     "retries": 0, "timeout": 10},
    {"id": "always-fails", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"],
     "retries": 1, "timeout": 10},
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks", help="JSON task file")
    parser.add_argument("--demo", action="store_true",
                        help="run the built-in demo tasks")
    parser.add_argument("--dry-run", action="store_true",
                        help="list tasks without running them")
    parser.add_argument("--skip-succeeded", action="store_true")
    parser.add_argument("--state", default="runner-state.json")
    parser.add_argument("--log", default="runs.log.jsonl")
    parser.add_argument("--report", help="write a Markdown report here")
    args = parser.parse_args(argv)

    if args.demo:
        tasks = DEMO_TASKS
    elif args.tasks:
        try:
            tasks = load_tasks(args.tasks)
        except (ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        parser.error("--tasks or --demo is required")

    if args.dry_run:
        for task in tasks:
            print(f"{task['id']}: {' '.join(task['argv'])} "
                  f"(retries={task.get('retries', 0)}, "
                  f"timeout={task.get('timeout')})")
        return 0

    state = load_state(args.state)
    results = run_all(tasks, state, args.skip_succeeded, args.log)
    if args.state:
        Path(args.state).write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8")
    if args.report:
        Path(args.report).write_text(render_markdown(results),
                                     encoding="utf-8")
    print(render_markdown(results))
    return 0 if all(r["status"] in ("ok", "skipped") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
