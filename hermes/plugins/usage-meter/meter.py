"""Explicit work-unit attribution over Hermes session usage."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

PLUGIN_NAME = "usage-meter"
WORK_UNIT_RE = re.compile(
    r"^forgejo:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):issue:(?P<issue>[1-9][0-9]*)$"
)
COUNTER_COLUMNS = (
    "api_call_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "estimated_cost_usd",
    "actual_cost_usd",
)
KEY_COLUMNS = (
    "session_id",
    "model",
    "billing_provider",
    "billing_base_url",
    "billing_mode",
    "task",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS work_units (
    work_unit TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    root_session_id TEXT NOT NULL,
    lineage_root_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL CHECK (status IN ('active', 'closing', 'finished')),
    pending_pr_number INTEGER,
    pending_merge_sha TEXT,
    pending_merged_at REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_open_work_unit_per_lineage
ON work_units(lineage_root_id) WHERE status IN ('active', 'closing');

CREATE TABLE IF NOT EXISTS usage_baselines (
    work_unit TEXT NOT NULL REFERENCES work_units(work_unit) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    billing_provider TEXT NOT NULL DEFAULT '',
    billing_base_url TEXT NOT NULL DEFAULT '',
    billing_mode TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    api_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    actual_cost_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (
        work_unit, session_id, model, billing_provider,
        billing_base_url, billing_mode, task
    )
);

CREATE TABLE IF NOT EXISTS merge_usage (
    repository TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    pr_number INTEGER NOT NULL,
    merge_sha TEXT NOT NULL UNIQUE,
    work_unit TEXT NOT NULL UNIQUE REFERENCES work_units(work_unit),
    started_at REAL NOT NULL,
    merged_at REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    api_calls INTEGER NOT NULL,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    model_breakdown TEXT NOT NULL,
    session_ids TEXT NOT NULL
);
"""


def connect_meter(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the meter database, creating its schema when needed."""
    if path is None:
        from plugins.plugin_storage import plugin_db

        conn = plugin_db(PLUGIN_NAME, "usage-meter.db")
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def connect_state(path: str | Path | None = None) -> sqlite3.Connection:
    """Open Hermes state read-only; the meter never migrates or writes it."""
    if path is None:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "state.db"
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Hermes state database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def parse_work_unit(work_unit: str) -> tuple[str, int]:
    match = WORK_UNIT_RE.fullmatch((work_unit or "").strip())
    if not match:
        raise ValueError(
            "work_unit must match forgejo:<owner>/<repository>:issue:<positive-number>"
        )
    return match.group("repository"), int(match.group("issue"))


def _require_session(state: sqlite3.Connection, session_id: str) -> None:
    if not session_id:
        raise ValueError("Hermes did not provide a current session_id")
    if state.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
        raise ValueError(f"session not found in Hermes state: {session_id}")


def _lineage_root_id(state: sqlite3.Connection, session_id: str) -> str:
    row = state.execute(
        """
        WITH RECURSIVE ancestors(id, parent_session_id) AS (
            SELECT id, parent_session_id FROM sessions WHERE id = ?
            UNION
            SELECT parent.id, parent.parent_session_id
            FROM sessions AS parent
            JOIN ancestors AS child ON parent.id = child.parent_session_id
        )
        SELECT id FROM ancestors ORDER BY parent_session_id IS NULL DESC LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return str(row[0]) if row else session_id


def _usage_rows(state: sqlite3.Connection, session_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = sorted(set(session_ids))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    columns = ", ".join((*KEY_COLUMNS, *COUNTER_COLUMNS, "cost_status", "cost_source"))
    rows = state.execute(
        f"SELECT {columns} FROM session_model_usage WHERE session_id IN ({placeholders})",
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _baseline_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(column, "") for column in KEY_COLUMNS)


def start_work_unit(
    meter: sqlite3.Connection,
    state: sqlite3.Connection,
    work_unit: str,
    session_id: str,
    *,
    started_at: float | None = None,
) -> dict[str, Any]:
    repository, issue_number = parse_work_unit(work_unit)
    _require_session(state, session_id)
    started_at = float(started_at if started_at is not None else time.time())
    lineage_root_id = _lineage_root_id(state, session_id)
    baseline = _usage_rows(state, [session_id])
    try:
        with meter:
            meter.execute(
                "INSERT INTO work_units "
                "(work_unit, repository, issue_number, root_session_id, lineage_root_id, "
                "started_at, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (work_unit, repository, issue_number, session_id, lineage_root_id, started_at),
            )
            meter.executemany(
                "INSERT INTO usage_baselines ("
                "work_unit, session_id, model, billing_provider, billing_base_url, "
                "billing_mode, task, api_call_count, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, reasoning_tokens, "
                "estimated_cost_usd, actual_cost_usd"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        work_unit,
                        *(row.get(column) or "" for column in KEY_COLUMNS),
                        *(row.get(column) or 0 for column in COUNTER_COLUMNS),
                    )
                    for row in baseline
                ],
            )
    except sqlite3.IntegrityError as exc:
        existing = meter.execute(
            "SELECT status FROM work_units WHERE work_unit = ?", (work_unit,)
        ).fetchone()
        if existing:
            raise ValueError(f"work unit already exists with status {existing['status']}") from exc
        active = meter.execute(
            "SELECT work_unit FROM work_units "
            "WHERE lineage_root_id = ? AND status IN ('active', 'closing')",
            (lineage_root_id,),
        ).fetchone()
        if active:
            raise ValueError(
                f"session already has active work unit: {active['work_unit']}"
            ) from exc
        raise
    return {
        "success": True,
        "action": "start",
        "work_unit": work_unit,
        "repository": repository,
        "issue_number": issue_number,
        "root_session_id": session_id,
        "lineage_root_id": lineage_root_id,
        "started_at": started_at,
        "baseline_rows": len(baseline),
    }


def _work_unit(meter: sqlite3.Connection, work_unit: str) -> sqlite3.Row:
    row = meter.execute("SELECT * FROM work_units WHERE work_unit = ?", (work_unit,)).fetchone()
    if row is None:
        raise ValueError(f"unknown work unit: {work_unit}")
    return row


def attributed_session_ids(state: sqlite3.Connection, root_session_id: str, started_at: float) -> list[str]:
    """Follow only compression and delegation edges rooted at this work unit."""
    rows = state.execute(
        """
        WITH RECURSIVE attributed(id) AS (
            SELECT ?
            UNION
            SELECT child.id
            FROM sessions AS child
            JOIN attributed AS parent_ids ON child.parent_session_id = parent_ids.id
            JOIN sessions AS parent ON parent.id = parent_ids.id
            WHERE child.started_at >= ?
              AND COALESCE(child.source, '') != 'tool'
              AND (
                    json_extract(CASE WHEN json_valid(child.model_config) THEN child.model_config ELSE '{}' END, '$._delegate_from') = parent_ids.id
                    OR (
                        parent.end_reason = 'compression'
                        AND COALESCE(json_extract(CASE WHEN json_valid(child.model_config) THEN child.model_config ELSE '{}' END, '$._delegate_from'), '') != parent_ids.id
                        AND COALESCE(json_extract(CASE WHEN json_valid(child.model_config) THEN child.model_config ELSE '{}' END, '$._branched_from'), '') != parent_ids.id
                        AND COALESCE(json_extract(CASE WHEN json_valid(child.model_config) THEN child.model_config ELSE '{}' END, '$._reset_from'), '') != parent_ids.id
                    )
              )
        )
        SELECT id FROM attributed ORDER BY id
        """,
        (root_session_id, started_at),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _completed_report(meter: sqlite3.Connection, unit: sqlite3.Row) -> dict[str, Any] | None:
    row = meter.execute(
        "SELECT * FROM merge_usage WHERE work_unit = ?", (unit["work_unit"],)
    ).fetchone()
    if row is None:
        return None
    return {
        "work_unit": unit["work_unit"],
        "repository": row["repository"],
        "issue_number": int(row["issue_number"]),
        "status": "finished",
        "started_at": float(row["started_at"]),
        "duration_seconds": max(0.0, float(row["merged_at"]) - float(row["started_at"])),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "cache_read_tokens": int(row["cache_read_tokens"]),
        "cache_write_tokens": int(row["cache_write_tokens"]),
        "reasoning_tokens": int(row["reasoning_tokens"]),
        "api_calls": int(row["api_calls"]),
        "estimated_cost_usd": row["estimated_cost_usd"],
        "actual_cost_usd": row["actual_cost_usd"],
        "models": json.loads(row["model_breakdown"]),
        "session_ids": json.loads(row["session_ids"]),
        "pull_request": int(row["pr_number"]),
        "merge_sha": row["merge_sha"],
        "merged_at": float(row["merged_at"]),
    }


def calculate_usage(
    meter: sqlite3.Connection,
    state: sqlite3.Connection,
    work_unit: str,
) -> dict[str, Any]:
    unit = _work_unit(meter, work_unit)
    if unit["status"] == "finished":
        completed = _completed_report(meter, unit)
        if completed is None:
            raise ValueError(f"finished work unit has no merge record: {work_unit}")
        return completed
    session_ids = attributed_session_ids(
        state, str(unit["root_session_id"]), float(unit["started_at"])
    )
    current_rows = _usage_rows(state, session_ids)
    baseline_rows = [
        dict(row)
        for row in meter.execute(
            "SELECT * FROM usage_baselines WHERE work_unit = ?", (work_unit,)
        ).fetchall()
    ]
    baseline = {_baseline_key(row): row for row in baseline_rows}

    breakdown: list[dict[str, Any]] = []
    totals = {column: 0.0 if column.endswith("usd") else 0 for column in COUNTER_COLUMNS}
    actual_available = False
    estimated_available = False
    for current in current_rows:
        prior = baseline.get(_baseline_key(current), {})
        usage: dict[str, Any] = {column: current.get(column) or "" for column in KEY_COLUMNS}
        for column in COUNTER_COLUMNS:
            delta = max(0, (current.get(column) or 0) - (prior.get(column) or 0))
            usage[column] = delta
            totals[column] += delta
        usage["cost_status"] = current.get("cost_status")
        usage["cost_source"] = current.get("cost_source")
        cost_status = str(usage["cost_status"] or "").lower()
        cost_source = str(usage["cost_source"] or "").lower()
        if usage["actual_cost_usd"] > 0 or cost_status == "actual":
            actual_available = True
        if (
            usage["estimated_cost_usd"] > 0
            or cost_status in {"estimated", "included"}
            or cost_source not in {"", "none", "unknown"}
        ):
            estimated_available = True
        if any(usage[column] for column in COUNTER_COLUMNS):
            breakdown.append(usage)

    breakdown.sort(key=lambda row: tuple(str(row[column]) for column in KEY_COLUMNS))
    return {
        "work_unit": work_unit,
        "repository": unit["repository"],
        "issue_number": int(unit["issue_number"]),
        "status": unit["status"],
        "started_at": float(unit["started_at"]),
        "duration_seconds": max(0.0, time.time() - float(unit["started_at"])),
        "input_tokens": int(totals["input_tokens"]),
        "output_tokens": int(totals["output_tokens"]),
        "cache_read_tokens": int(totals["cache_read_tokens"]),
        "cache_write_tokens": int(totals["cache_write_tokens"]),
        "reasoning_tokens": int(totals["reasoning_tokens"]),
        "api_calls": int(totals["api_call_count"]),
        "estimated_cost_usd": (
            round(float(totals["estimated_cost_usd"]), 8) if estimated_available else None
        ),
        "actual_cost_usd": round(float(totals["actual_cost_usd"]), 8) if actual_available else None,
        "models": breakdown,
        "session_ids": session_ids,
    }


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def pr_comment(report: dict[str, Any]) -> str:
    marker = {
        "input": report["input_tokens"],
        "output": report["output_tokens"],
        "cache_read": report["cache_read_tokens"],
        "cache_write": report["cache_write_tokens"],
        "reasoning": report["reasoning_tokens"],
        "api_calls": report["api_calls"],
    }
    cost = report.get("estimated_cost_usd")
    cost_text = "unavailable" if cost is None else f"${cost:.4f}"
    return "\n".join(
        (
            "### Agent usage",
            f"<!-- hermes-merge-usage:v1 {json.dumps(marker, separators=(',', ':'))} -->",
            f"- Input: {_fmt_int(report['input_tokens'])}",
            f"- Output: {_fmt_int(report['output_tokens'])}",
            f"- Cache read: {_fmt_int(report['cache_read_tokens'])}",
            f"- Cache write: {_fmt_int(report['cache_write_tokens'])}",
            f"- Reasoning: {_fmt_int(report['reasoning_tokens'])}",
            f"- API calls: {_fmt_int(report['api_calls'])}",
            f"- Estimated cost: {cost_text}",
        )
    )


def finish_work_unit(
    meter: sqlite3.Connection,
    state: sqlite3.Connection,
    work_unit: str,
    pr_number: int,
    merge_sha: str,
    *,
    session_id: str,
    merged_at: float | None = None,
) -> dict[str, Any]:
    """Arm finalization; post_llm_call seals usage after Hermes drains counters."""
    if int(pr_number) <= 0:
        raise ValueError("pr_number must be positive")
    merge_sha = (merge_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
        raise ValueError("merge_sha must be a full 40-character hexadecimal commit SHA")
    unit = _work_unit(meter, work_unit)
    if unit["status"] != "active":
        raise ValueError(f"work unit is not active: {work_unit}")
    if session_id not in attributed_session_ids(
        state, str(unit["root_session_id"]), float(unit["started_at"])
    ):
        raise ValueError("finish must be called from the metered session lineage")
    merged_at = float(merged_at if merged_at is not None else time.time())
    with meter:
        changed = meter.execute(
            "UPDATE work_units SET status = 'closing', pending_pr_number = ?, "
            "pending_merge_sha = ?, pending_merged_at = ? "
            "WHERE work_unit = ? AND status = 'active'",
            (int(pr_number), merge_sha, merged_at, work_unit),
        ).rowcount
        if changed != 1:
            raise ValueError(f"work unit is not active: {work_unit}")
    return {
        "success": True,
        "action": "finish",
        "status": "closing",
        "work_unit": work_unit,
        "pull_request": int(pr_number),
        "merge_sha": merge_sha,
        "merged_at": merged_at,
        "message": (
            "Finish is armed. Hermes will seal the usage record after this turn "
            "drains token accounting. Call status in the next turn to obtain "
            "pr_comment_markdown."
        ),
    }


def finalize_closing_work_units(
    meter: sqlite3.Connection,
    state: sqlite3.Connection,
    session_id: str,
) -> list[str]:
    """Seal closing work units after turn-finalization has persisted counters."""
    finalized: list[str] = []
    units = meter.execute(
        "SELECT * FROM work_units WHERE status = 'closing' ORDER BY started_at"
    ).fetchall()
    for unit in units:
        if session_id not in attributed_session_ids(
            state, str(unit["root_session_id"]), float(unit["started_at"])
        ):
            continue
        work_unit = str(unit["work_unit"])
        report = calculate_usage(meter, state, work_unit)
        pr_number = int(unit["pending_pr_number"] or 0)
        merge_sha = str(unit["pending_merge_sha"] or "")
        merged_at = float(unit["pending_merged_at"] or time.time())
        if pr_number <= 0 or not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
            continue
        with meter:
            meter.execute(
                "INSERT INTO merge_usage ("
                "repository, issue_number, pr_number, merge_sha, work_unit, started_at, merged_at, "
                "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, "
                "api_calls, estimated_cost_usd, actual_cost_usd, model_breakdown, session_ids"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report["repository"], report["issue_number"], pr_number, merge_sha,
                    work_unit, report["started_at"], merged_at, report["input_tokens"],
                    report["output_tokens"], report["cache_read_tokens"],
                    report["cache_write_tokens"], report["reasoning_tokens"], report["api_calls"],
                    report["estimated_cost_usd"], report["actual_cost_usd"],
                    json.dumps(report["models"], sort_keys=True, separators=(",", ":")),
                    json.dumps(report["session_ids"], separators=(",", ":")),
                ),
            )
            meter.execute(
                "UPDATE work_units SET status = 'finished', finished_at = ? WHERE work_unit = ?",
                (merged_at, work_unit),
            )
        finalized.append(work_unit)
    return finalized


def list_records(meter: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    active = [dict(row) for row in meter.execute(
        "SELECT * FROM work_units WHERE status IN ('active', 'closing') "
        "ORDER BY started_at DESC LIMIT ?", (limit,)
    )]
    completed_rows = meter.execute(
        "SELECT * FROM merge_usage ORDER BY merged_at DESC LIMIT ?", (limit,)
    ).fetchall()
    completed = []
    for row in completed_rows:
        item = dict(row)
        item["models"] = json.loads(item.pop("model_breakdown"))
        item["session_ids"] = json.loads(item["session_ids"])
        completed.append(item)
    return {"success": True, "action": "list", "active": active, "completed": completed}
