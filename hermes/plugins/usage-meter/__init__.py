"""Hermes usage-meter plugin registration."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from . import meter, schemas

logger = logging.getLogger(__name__)


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _handle(params: dict[str, Any], **kwargs: Any) -> str:
    action = str(params.get("action") or "").strip().lower()
    work_unit = str(params.get("work_unit") or "").strip()
    meter_db = meter.connect_meter()
    try:
        if action == "list":
            return _result(meter.list_records(meter_db, params.get("limit", 20)))
        if action not in {"start", "status", "finish"}:
            raise ValueError("action must be one of: start, status, finish, list")
        if not work_unit:
            raise ValueError(f"work_unit is required for {action}")
        state_db = meter.connect_state()
        try:
            if action == "start":
                payload = meter.start_work_unit(
                    meter_db, state_db, work_unit, str(kwargs.get("session_id") or "")
                )
            elif action == "status":
                payload = meter.calculate_usage(meter_db, state_db, work_unit)
                payload.update({"success": True, "action": "status"})
                if payload.get("status") == "finished":
                    payload["pr_comment_markdown"] = meter.pr_comment(payload)
            else:
                payload = meter.finish_work_unit(
                    meter_db,
                    state_db,
                    work_unit,
                    int(params.get("pr_number") or 0),
                    str(params.get("merge_sha") or ""),
                    session_id=str(kwargs.get("session_id") or ""),
                )
            return _result(payload)
        finally:
            state_db.close()
    except (FileNotFoundError, ValueError, sqlite3.Error) as exc:
        return _result({"success": False, "action": action, "error": str(exc)})
    finally:
        meter_db.close()


def _on_post_llm_call(session_id: str = "", **_: Any) -> None:
    """Finalize only after Hermes has drained queued usage into state.db."""
    if not session_id:
        return
    meter_db = state_db = None
    try:
        meter_db = meter.connect_meter()
        state_db = meter.connect_state()
        meter.finalize_closing_work_units(meter_db, state_db, session_id)
    except Exception:
        logger.exception("usage-meter deferred finalization failed")
    finally:
        if state_db is not None:
            state_db.close()
        if meter_db is not None:
            meter_db.close()


def register(ctx) -> None:
    # Create/migrate the analytics DB at plugin load so setup failures are visible.
    conn = meter.connect_meter()
    conn.close()
    ctx.register_tool(
        name="usage_meter",
        toolset="usage_meter",
        schema=schemas.USAGE_METER,
        handler=_handle,
        emoji="📏",
    )
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_system_prompt_section(
        "usage-meter.discovery",
        (
            "The usage-meter plugin is installed and enabled. For software-delivery work, "
            "do not conclude that `usage_meter` is unavailable merely because it is absent "
            "from the initially loaded tool list. It is a deferred tool: use `tool_search` "
            "for `usage meter work unit`, load `usage_meter` with `tool_describe`, then invoke "
            "it with `tool_call`. Start an explicit work unit before issue-specific work and "
            "follow the plugin skill for status and finalization."
        ),
        max_chars=700,
    )
    skill_path = Path(__file__).parent / "skills" / "usage-meter" / "SKILL.md"
    ctx.register_skill(
        "usage-meter",
        skill_path,
        description="Attribute delivery usage with explicit work units.",
    )
