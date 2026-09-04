from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("usage_meter_core", PLUGIN_DIR / "meter.py")
meter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(meter)

STATE_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'webui',
    model_config TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT
);
CREATE TABLE session_model_usage (
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
    cost_status TEXT,
    cost_source TEXT
);
"""


def add_session(conn, session_id, *, parent=None, started=1, reason=None, config=None, source="webui"):
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL, ?)",
        (session_id, source, json.dumps(config or {}), parent, started, reason),
    )


def add_usage(
    conn,
    session_id,
    *,
    model="gpt-test",
    provider="test-provider",
    task="main",
    calls=1,
    input_tokens=0,
    output_tokens=0,
    cache_read=0,
    cache_write=0,
    reasoning=0,
    estimated=0.0,
    actual=0.0,
    cost_status="estimated",
):
    conn.execute(
        "INSERT INTO session_model_usage VALUES (?, ?, ?, '', 'api', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test')",
        (
            session_id,
            model,
            provider,
            task,
            calls,
            input_tokens,
            output_tokens,
            cache_read,
            cache_write,
            reasoning,
            estimated,
            actual,
            cost_status,
        ),
    )


class UsageMeterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state_path = root / "state.db"
        state = sqlite3.connect(self.state_path)
        state.executescript(STATE_SCHEMA)
        add_session(state, "root", started=1, reason="compression")
        add_usage(
            state,
            "root",
            calls=2,
            input_tokens=100,
            output_tokens=10,
            cache_read=40,
            estimated=0.1,
        )
        state.commit()
        state.close()
        self.meter = meter.connect_meter(root / "meter.db")
        self.state = meter.connect_state(self.state_path)

    def tearDown(self):
        self.state.close()
        self.meter.close()
        self.tmp.cleanup()

    def test_schema_and_work_unit_validation(self):
        tables = {
            row[0]
            for row in self.meter.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({"work_units", "usage_baselines", "merge_usage"}.issubset(tables))
        self.assertEqual(meter.parse_work_unit("forgejo:jake/shallwego:issue:29"), ("jake/shallwego", 29))
        with self.assertRaises(ValueError):
            meter.parse_work_unit("forgejo:jake/shallwego:issue:0")

    def test_one_lineage_cannot_double_attribute_active_work(self):
        meter.start_work_unit(
            self.meter,
            self.state,
            "forgejo:jake/shallwego:issue:29",
            "root",
            started_at=100,
        )
        writer = sqlite3.connect(self.state_path)
        add_session(writer, "continuation", parent="root", started=110)
        writer.commit()
        writer.close()
        with self.assertRaisesRegex(ValueError, "already has active work unit"):
            meter.start_work_unit(
                self.meter,
                self.state,
                "forgejo:jake/shallwego:issue:30",
                "continuation",
                started_at=120,
            )

    def test_live_usage_follows_only_delegate_and_compression_lineage(self):
        meter.start_work_unit(
            self.meter,
            self.state,
            "forgejo:jake/shallwego:issue:29",
            "root",
            started_at=100,
        )
        writer = sqlite3.connect(self.state_path)
        writer.execute(
            "UPDATE session_model_usage SET api_call_count=3, input_tokens=150, output_tokens=15, "
            "cache_read_tokens=50, estimated_cost_usd=0.15 WHERE session_id='root'"
        )
        add_session(writer, "compressed", parent="root", started=110)
        add_usage(writer, "compressed", calls=2, input_tokens=20, output_tokens=2, estimated=0.02)
        add_session(
            writer,
            "delegate",
            parent="root",
            started=120,
            reason="compression",
            config={"_delegate_from": "root"},
        )
        add_usage(
            writer,
            "delegate",
            model="review-model",
            task="review",
            calls=3,
            input_tokens=30,
            output_tokens=3,
            reasoning=4,
            estimated=0.03,
            actual=0.025,
            cost_status="actual",
        )
        # Compression copies the original delegate marker; it is not a fresh delegate edge.
        add_session(
            writer,
            "delegate-compressed",
            parent="delegate",
            started=130,
            config={"_delegate_from": "root"},
        )
        add_usage(writer, "delegate-compressed", calls=1, input_tokens=10, output_tokens=1, estimated=0.01)
        add_session(writer, "branch", parent="root", started=140, config={"_branched_from": "root"})
        add_usage(writer, "branch", input_tokens=999)
        add_session(writer, "reset", parent="root", started=150, config={"_reset_from": "root"})
        add_usage(writer, "reset", input_tokens=999)
        add_session(writer, "tool-child", parent="root", started=160, source="tool")
        add_usage(writer, "tool-child", input_tokens=999)
        add_session(
            writer,
            "old-delegate",
            parent="root",
            started=50,
            config={"_delegate_from": "root"},
        )
        add_usage(writer, "old-delegate", input_tokens=999)
        writer.commit()
        writer.close()

        report = meter.calculate_usage(self.meter, self.state, "forgejo:jake/shallwego:issue:29")
        self.assertEqual(report["session_ids"], ["compressed", "delegate", "delegate-compressed", "root"])
        self.assertEqual(report["input_tokens"], 110)
        self.assertEqual(report["output_tokens"], 11)
        self.assertEqual(report["cache_read_tokens"], 10)
        self.assertEqual(report["reasoning_tokens"], 4)
        self.assertEqual(report["api_calls"], 7)
        self.assertAlmostEqual(report["estimated_cost_usd"], 0.11)
        self.assertAlmostEqual(report["actual_cost_usd"], 0.025)
        self.assertEqual({row["task"] for row in report["models"]}, {"main", "review"})

    def test_unknown_and_included_costs_remain_distinct(self):
        work_unit = "forgejo:jake/shallwego:issue:29"
        meter.start_work_unit(self.meter, self.state, work_unit, "root", started_at=100)
        writer = sqlite3.connect(self.state_path)
        writer.execute(
            "UPDATE session_model_usage SET cost_status='unknown', cost_source='none', "
            "estimated_cost_usd=0 WHERE session_id='root'"
        )
        writer.commit()
        writer.close()
        report = meter.calculate_usage(self.meter, self.state, work_unit)
        self.assertIsNone(report["estimated_cost_usd"])

        writer = sqlite3.connect(self.state_path)
        writer.execute(
            "UPDATE session_model_usage SET cost_status='included', "
            "cost_source='subscription', estimated_cost_usd=0 WHERE session_id='root'"
        )
        writer.commit()
        writer.close()
        report = meter.calculate_usage(self.meter, self.state, work_unit)
        self.assertEqual(report["estimated_cost_usd"], 0.0)

    def test_finish_defers_until_turn_finalization_and_freezes_counts(self):
        work_unit = "forgejo:jake/shallwego:issue:29"
        meter.start_work_unit(self.meter, self.state, work_unit, "root", started_at=100)
        with self.assertRaisesRegex(ValueError, "metered session lineage"):
            meter.finish_work_unit(
                self.meter,
                self.state,
                work_unit,
                57,
                "72332d64bf3d8da272f4ea78a5389769ccbaf516",
                session_id="unrelated",
            )
        armed = meter.finish_work_unit(
            self.meter,
            self.state,
            work_unit,
            57,
            "72332d64bf3d8da272f4ea78a5389769ccbaf516",
            session_id="root",
            merged_at=200,
        )
        self.assertEqual(armed["status"], "closing")
        self.assertIsNone(self.meter.execute("SELECT * FROM merge_usage").fetchone())

        # Hermes drains the API call that selected finish and the final answer
        # before post_llm_call invokes the meter finalizer.
        writer = sqlite3.connect(self.state_path)
        writer.execute(
            "UPDATE session_model_usage SET api_call_count=4, input_tokens=175, "
            "output_tokens=25, estimated_cost_usd=0.175 WHERE session_id='root'"
        )
        writer.commit()
        writer.close()
        self.assertEqual(
            meter.finalize_closing_work_units(self.meter, self.state, "root"),
            [work_unit],
        )

        row = self.meter.execute("SELECT * FROM merge_usage").fetchone()
        self.assertEqual(row["repository"], "jake/shallwego")
        self.assertEqual(row["pr_number"], 57)
        self.assertEqual(row["input_tokens"], 75)
        self.assertEqual(row["output_tokens"], 15)
        self.assertIsNone(row["actual_cost_usd"])
        self.assertEqual(json.loads(row["session_ids"]), ["root"])
        self.assertIsInstance(json.loads(row["model_breakdown"]), list)

        # A completed work unit stays immutable when later unrelated work uses
        # the same conversation.
        writer = sqlite3.connect(self.state_path)
        writer.execute(
            "UPDATE session_model_usage SET input_tokens=9999 WHERE session_id='root'"
        )
        writer.commit()
        writer.close()
        completed = meter.calculate_usage(self.meter, self.state, work_unit)
        self.assertEqual(completed["status"], "finished")
        self.assertEqual(completed["input_tokens"], 75)
        self.assertEqual(completed["merge_sha"], armed["merge_sha"])
        self.assertIn("hermes-merge-usage:v1", meter.pr_comment(completed))

        with self.assertRaises(ValueError):
            meter.finish_work_unit(
                self.meter,
                self.state,
                work_unit,
                57,
                "72332d64bf3d8da272f4ea78a5389769ccbaf516",
                session_id="root",
            )

    def test_concurrent_finish_cannot_reopen_finished_work_unit(self):
        work_unit = "forgejo:jake/shallwego:issue:29"
        meter.start_work_unit(self.meter, self.state, work_unit, "root", started_at=100)
        original = meter.attributed_session_ids

        def finalize_between_read_and_compare_and_set(state, root, started):
            with self.meter:
                self.meter.execute(
                    "UPDATE work_units SET status='finished', finished_at=150 "
                    "WHERE work_unit=?",
                    (work_unit,),
                )
            return original(state, root, started)

        with mock.patch.object(
            meter, "attributed_session_ids", side_effect=finalize_between_read_and_compare_and_set
        ):
            with self.assertRaisesRegex(ValueError, "not active"):
                meter.finish_work_unit(
                    self.meter,
                    self.state,
                    work_unit,
                    58,
                    "82332d64bf3d8da272f4ea78a5389769ccbaf516",
                    session_id="root",
                )
        row = self.meter.execute(
            "SELECT status, pending_pr_number, pending_merge_sha FROM work_units "
            "WHERE work_unit=?",
            (work_unit,),
        ).fetchone()
        self.assertEqual(row["status"], "finished")
        self.assertIsNone(row["pending_pr_number"])
        self.assertIsNone(row["pending_merge_sha"])

    def test_full_merge_sha_is_required(self):
        work_unit = "forgejo:jake/shallwego:issue:29"
        meter.start_work_unit(self.meter, self.state, work_unit, "root", started_at=100)
        with self.assertRaisesRegex(ValueError, "40-character"):
            meter.finish_work_unit(
                self.meter, self.state, work_unit, 57, "72332d6", session_id="root"
            )


if __name__ == "__main__":
    unittest.main()
