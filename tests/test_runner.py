"""Tests for agent_task_runner: real subprocess runs, no mocks of the core."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_task_runner as runner

PY = sys.executable


def task(task_id, argv, **kw):
    d = {"id": task_id, "argv": argv}
    d.update(kw)
    return d


class TestValidation(unittest.TestCase):
    def test_shell_string_rejected(self):
        # load_tasks validates via a temp file
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as fh:
            json.dump([{"id": "x", "argv": "echo hi; rm -rf /"}], fh)
            path = fh.name
        with self.assertRaises(ValueError):
            runner.load_tasks(path)

    def test_empty_argv_rejected(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as fh:
            json.dump([{"id": "x", "argv": []}], fh)
            path = fh.name
        with self.assertRaises(ValueError):
            runner.load_tasks(path)


class TestRun(unittest.TestCase):
    def test_success(self):
        result = runner.run_one(
            task("ok", [PY, "-c", "print('hi')"]), None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["attempts"], 1)

    def test_failure_retries(self):
        result = runner.run_one(
            task("fail", [PY, "-c", "import sys; sys.exit(3)"],
                 retries=2), None)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["exit_code"], 3)

    def test_timeout_reported_not_hung(self):
        result = runner.run_one(
            task("slow", [PY, "-c", "import time; time.sleep(30)"],
                 timeout=1), None)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["timed_out"])

    def test_missing_command(self):
        result = runner.run_one(
            task("nope", ["definitely-not-a-real-binary-xyz"]), None)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["exit_code"])

    def test_injection_is_literal_argv(self):
        # If this were run through a shell, ';' would split commands.
        # With argv-only execution it is just an argument to python -c,
        # which fails safely instead of running a second command.
        result = runner.run_one(
            task("inj", [PY, "-c", "print(1); print(2)"]), None)
        self.assertEqual(result["status"], "ok")

    def test_skip_succeeded(self):
        tasks = [task("ok", [PY, "-c", "print('hi')"])]
        state = {}
        # run_all returns results; state is mutated in place.
        results = runner.run_all(tasks, state, False, None)
        self.assertEqual(results[0]["status"], "ok")
        results2 = runner.run_all(tasks, state, True, None)
        self.assertEqual(results2[0]["status"], "skipped")
        # Changing argv invalidates the skip.
        tasks_changed = [task("ok", [PY, "-c", "print('bye')"])]
        results3 = runner.run_all(tasks_changed, state, True, None)
        self.assertEqual(results3[0]["status"], "ok")

    def test_report_counts(self):
        results = [
            {"id": "a", "status": "ok", "attempts": 1, "duration_s": 0.1},
            {"id": "b", "status": "failed", "attempts": 2, "duration_s": 0.2},
        ]
        md = runner.render_markdown(results)
        self.assertIn("1 ok", md)
        self.assertIn("1 failed", md)


if __name__ == "__main__":
    unittest.main()
