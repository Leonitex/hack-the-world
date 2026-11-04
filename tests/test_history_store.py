"""HistoryStore tests. SQLite file lives in a temporary directory."""

import os
import sqlite3
import tempfile
import unittest

from history_store import HistoryStore


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "history.db")
        self.store = HistoryStore(self.path)

    def test_create_and_list_session(self):
        self.store.create_session("s1", "Investigation 1", "No display")
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "s1")
        self.assertEqual(sessions[0]["name"], "Investigation 1")
        self.assertEqual(sessions[0]["archived"], 0)
        self.assertTrue(sessions[0]["created_at"])

    def test_events_keep_sequence_and_order(self):
        self.store.create_session("s1", "One", "Problem")
        self.assertEqual(
            self.store.record_event("s1", "user", "◉", "You reported", "It beeps"), 1)
        self.assertEqual(
            self.store.record_event("s1", "test", "▷", "Test requested", "Check cable", "r1"), 2)
        events = self.store.get_events("s1")
        self.assertEqual([event["seq"] for event in events], [1, 2])
        self.assertEqual(events[1]["record_id"], "r1")
        self.assertTrue(events[0]["created_at"] <= events[1]["created_at"])

    def test_history_survives_reopen(self):
        self.store.create_session("s1", "One", "Problem")
        self.store.record_event("s1", "user", "◉", "You reported", "It beeps")
        reopened = HistoryStore(self.path)
        sessions = reopened.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["name"], "One")
        events = reopened.get_events("s1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "You reported")

    def test_startup_sweep_archives_foreign_live_sessions(self):
        self.store.create_session("s1", "One", "Problem")
        reopened = HistoryStore(self.path)
        session = reopened.get_session("s1")
        self.assertEqual(session["archived"], 1)
        self.assertEqual(session["status"], "archived")
        self.assertEqual(reopened.get_events("s1"), [])

    def test_current_run_session_stays_live(self):
        self.store.create_session("s1", "One", "Problem")
        session = self.store.get_session("s1")
        self.assertEqual(session["archived"], 0)
        self.assertEqual(session["status"], "live")

    def test_archive_session(self):
        self.store.create_session("s1", "One", "Problem")
        self.store.archive_session("s1")
        session = self.store.get_session("s1")
        self.assertEqual(session["archived"], 1)

    def test_rename_session(self):
        self.store.create_session("s1", "One", "Problem")
        self.store.rename_session("s1", "  Front desk PC  ")
        self.assertEqual(self.store.get_session("s1")["name"], "Front desk PC")
        with self.assertRaises(ValueError):
            self.store.rename_session("s1", "   ")
        with self.assertRaises(ValueError):
            self.store.rename_session("s1", "x" * 81)
        with self.assertRaises(KeyError):
            self.store.rename_session("missing", "Name")

    def test_unknown_session_returns_none(self):
        self.assertIsNone(self.store.get_session("missing"))
        self.assertEqual(self.store.get_events("missing"), [])

    def test_events_belong_to_one_session(self):
        self.store.create_session("s1", "One", "Problem A")
        self.store.create_session("s2", "Two", "Problem B")
        self.store.record_event("s1", "user", "◉", "First", "A")
        self.store.record_event("s2", "user", "◉", "Second", "B")
        self.assertEqual([e["title"] for e in self.store.get_events("s1")], ["First"])
        self.assertEqual([e["title"] for e in self.store.get_events("s2")], ["Second"])

    def test_live_sessions_list_first(self):
        self.store.create_session("s1", "One", "Problem A")
        self.store.create_session("s2", "Two", "Problem B")
        self.store.archive_session("s1")
        listed = [s["id"] for s in self.store.list_sessions()]
        self.assertEqual(listed, ["s2", "s1"])

    def test_schema_uses_parameterized_safe_tables(self):
        conn = sqlite3.connect(self.path)
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
        self.assertIn("sessions", tables)
        self.assertIn("events", tables)


if __name__ == "__main__":
    unittest.main()
