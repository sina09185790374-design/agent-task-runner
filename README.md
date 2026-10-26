# agent-task-runner

A tiny, idempotent task runner for local agents — one Python file, stdlib only, no network, no API keys.

Pattern (patterns only, original code): one small, focused CLI built for agents (as popularized by agent-browser-style tools) + a learn-by-building execute/observe/retry loop + reusable task units (as in skill-pack thinking). Each task is a self-contained unit with its own retries and timeout.

## Why it exists

Agents (and cron jobs, and shop PCs) need to run a list of commands reliably: retry the flaky one, time out the hung one, skip the one that already succeeded, and leave an audit trail. This does exactly that and nothing else.

## Safety rules (deliberate)

1. **Commands are argv lists, never shell strings.** There is no `shell=True` anywhere — `; rm -rf /` is a literal argument that fails, not a second command.
2. **No network, no keys.** The runner never reads `.env` (see `.env.example`).
3. **Idempotent reruns:** with `--skip-succeeded`, a task that already succeeded for the exact same argv is skipped next run. State is a plain JSON file you can read and delete.

## Usage

```bash
python3 agent_task_runner.py --tasks tasks.example.json
python3 agent_task_runner.py --tasks tasks.json --skip-succeeded
python3 agent_task_runner.py --tasks tasks.json --dry-run
python3 agent_task_runner.py --demo
python3 agent_task_runner.py --tasks tasks.json --report report.md
```

Task file: a JSON list of `{"id", "argv", "retries", "timeout", "cwd"}` — see `tasks.example.json`.

Exit code: 0 when every executed task succeeded (or was skipped), 1 when any task failed, 2 on bad input. Every attempt is appended as one JSON line to `runs.log.jsonl`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT — see `LICENSE`.

---

# agent-task-runner (فارسی)

یک اجراکننده‌ی کوچک و قابل‌تکرار برای وظایف ایجنت‌های محلی — فقط یک فایل پایتون، فقط کتابخانه استاندارد، بدون شبکه و بدون کلید API.

**الگو:** یک ابزار خط فرمان کوچک و متمرکز برای ایجنت‌ها + چرخه‌ی اجرا/مشاهده/تلاش مجدد + واحدهای وظیفه‌ی قابل‌استفاده‌ی مجدد.

**قوانین امنیتی:**

1. دستورها فقط به‌صورت لیست آرگومان اجرا می‌شوند، هرگز رشته‌ی شل — پس `; rm -rf /` یک آرگومان بی‌اثر است، نه یک دستور دوم.
2. بدون شبکه و بدون کلید؛ اجراکننده `.env` را نمی‌خواند.
3. اجرای تکراری بی‌خطر است: با `--skip-succeeded` وظیفه‌ای که با همان دستور قبلاً موفق شده، دوباره اجرا نمی‌شود.

## اجرا

```bash
python3 agent_task_runner.py --tasks tasks.example.json
python3 agent_task_runner.py --tasks tasks.json --skip-succeeded
python3 agent_task_runner.py --demo
```

## تست

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT — see `LICENSE`.
