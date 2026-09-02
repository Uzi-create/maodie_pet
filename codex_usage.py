from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CodexUsageError(RuntimeError):
    """Raised when Codex account usage cannot be read safely."""


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float
    window_duration_mins: int
    resets_at: int | None


@dataclass(frozen=True)
class CodexUsageReport:
    plan_type: str | None
    five_hour: UsageWindow | None
    weekly: UsageWindow | None
    lifetime_tokens: int | None
    peak_daily_tokens: int | None
    current_streak_days: int | None
    reset_credits: int | None


def _find_codex() -> str:
    executable = shutil.which("codex")
    if executable:
        return executable

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if candidate.is_file():
            return str(candidate)

    if sys.platform == "darwin":
        mac_candidates = (
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path.home() / "Applications/Codex.app/Contents/Resources/codex",
        )
        for candidate in mac_candidates:
            if candidate.is_file():
                return str(candidate)

    raise CodexUsageError("没找到 Codex。先确认 Codex 桌面端已经安装并登录。")


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise CodexUsageError("Codex app-server 没有可用的输入通道。")
    process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_messages(
    process: subprocess.Popen[str],
    messages: queue.Queue[dict[str, Any] | BaseException],
) -> None:
    try:
        if process.stdout is None:
            raise CodexUsageError("Codex app-server 没有可用的输出通道。")
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue
    except BaseException as exc:  # pragma: no cover - defensive pipe handling
        messages.put(exc)


def _wait_for_ids(
    messages: queue.Queue[dict[str, Any] | BaseException],
    wanted_ids: set[int],
    deadline: float,
) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    while wanted_ids - responses.keys():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexUsageError("Codex 查账超时了。它可能没登录，也可能又在装死。")
        try:
            message = messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise CodexUsageError("Codex 查账超时了。它可能没登录，也可能又在装死。") from exc
        if isinstance(message, BaseException):
            raise CodexUsageError(f"读取 Codex 返回值失败：{message}") from message
        message_id = message.get("id")
        if message_id not in wanted_ids:
            continue
        if "error" in message:
            error = message.get("error") or {}
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise CodexUsageError(f"Codex 拒绝交账：{detail or '未知错误'}")
        responses[int(message_id)] = message.get("result") or {}
    return responses


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _window(value: Any) -> UsageWindow | None:
    if not isinstance(value, dict):
        return None
    used = _number(value.get("usedPercent"))
    duration = _number(value.get("windowDurationMins"))
    reset = _number(value.get("resetsAt"))
    if used is None or duration is None:
        return None
    return UsageWindow(
        used_percent=max(0.0, min(100.0, used)),
        window_duration_mins=max(0, int(duration)),
        resets_at=int(reset) if reset is not None else None,
    )


def _pick_bucket(rate_result: dict[str, Any]) -> dict[str, Any]:
    buckets = rate_result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict):
        codex_bucket = buckets.get("codex")
        if isinstance(codex_bucket, dict):
            return codex_bucket
        candidates = [value for value in buckets.values() if isinstance(value, dict)]
        candidates.sort(
            key=lambda item: int(item.get("primary") is not None)
            + int(item.get("secondary") is not None),
            reverse=True,
        )
        if candidates:
            return candidates[0]

    legacy = rate_result.get("rateLimits")
    return legacy if isinstance(legacy, dict) else {}


def _normalise_report(responses: dict[int, dict[str, Any]]) -> CodexUsageReport:
    rate_result = responses.get(1, {})
    usage_result = responses.get(2, {})
    account_result = responses.get(3, {})
    bucket = _pick_bucket(rate_result)

    windows = [
        result
        for result in (_window(bucket.get("primary")), _window(bucket.get("secondary")))
        if result is not None
    ]
    windows.sort(key=lambda item: item.window_duration_mins)
    five_hour = min(windows, key=lambda item: abs(item.window_duration_mins - 300), default=None)
    weekly = min(windows, key=lambda item: abs(item.window_duration_mins - 10080), default=None)
    if five_hour is weekly and len(windows) == 1:
        if windows[0].window_duration_mins >= 24 * 60:
            five_hour = None
        else:
            weekly = None

    account = account_result.get("account")
    account_plan = account.get("planType") if isinstance(account, dict) else None
    plan_type = bucket.get("planType") or account_plan

    summary = usage_result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    reset_credit_data = rate_result.get("rateLimitResetCredits")
    reset_credits = (
        reset_credit_data.get("availableCount")
        if isinstance(reset_credit_data, dict)
        else None
    )

    def optional_int(value: Any) -> int | None:
        number = _number(value)
        return int(number) if number is not None else None

    return CodexUsageReport(
        plan_type=str(plan_type) if plan_type else None,
        five_hour=five_hour,
        weekly=weekly,
        lifetime_tokens=optional_int(summary.get("lifetimeTokens")),
        peak_daily_tokens=optional_int(summary.get("peakDailyTokens")),
        current_streak_days=optional_int(summary.get("currentStreakDays")),
        reset_credits=optional_int(reset_credits),
    )


def fetch_codex_usage(timeout: float = 12.0) -> CodexUsageReport:
    """Read the signed-in ChatGPT plan usage through Codex's local app-server."""

    deadline = time.monotonic() + max(2.0, timeout)
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [_find_codex(), "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creation_flags,
    )
    messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
    reader = threading.Thread(
        target=_read_messages,
        args=(process, messages),
        name="maodie-codex-reader",
        daemon=True,
    )
    reader.start()

    try:
        _send(
            process,
            {
                "method": "initialize",
                "id": 0,
                "params": {
                    "clientInfo": {
                        "name": "maodie_pet",
                        "title": "Maodie Pet",
                        "version": "0.2.0",
                    }
                },
            },
        )
        _wait_for_ids(messages, {0}, deadline)
        _send(process, {"method": "initialized", "params": {}})
        _send(process, {"method": "account/rateLimits/read", "id": 1})
        _send(process, {"method": "account/usage/read", "id": 2})
        _send(
            process,
            {
                "method": "account/read",
                "id": 3,
                "params": {"refreshToken": False},
            },
        )
        responses = _wait_for_ids(messages, {1, 2, 3}, deadline)
        return _normalise_report(responses)
    except FileNotFoundError as exc:
        raise CodexUsageError("没找到 Codex 可执行文件。") from exc
    except OSError as exc:
        raise CodexUsageError(f"启动 Codex app-server 失败：{exc}") from exc
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)


if __name__ == "__main__":
    print(fetch_codex_usage())
