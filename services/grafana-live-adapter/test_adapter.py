import json
import tempfile
import unittest
from pathlib import Path

from adapter import AdapterState, GrafanaPushError, LiveAdapter, snapshot_lines, validate_snapshot


def fixture(revision=7, quality="ACTUAL", k1=100.0):
    return {
        "schemaVersion": 1,
        "revision": revision,
        "dataRevision": 6,
        "generatedAt": "2026-09-16T10:00:00Z",
        "lastEventId": "event-6",
        "quality": quality,
        "valid": quality == "ACTUAL",
        "kpis": {
            "B-K1": {"value": k1, "unit": "percent", "sample": 1 if k1 is not None else 0, "state": "SANO" if k1 == 100 else "SIN MUESTRA"},
            "B-K2": {"value": {"USD": "0"}, "unit": "demo_money_by_currency", "sample": 1, "state": "SANO"},
            "B-K3": {"value": {"USD": "60"}, "unit": "demo_money_by_currency", "sample": 1, "state": "INCUMPLIDO"},
        },
        "alerts": {
            "B-K1": {"active": False, "changedAt": "2026-09-16T10:00:00Z"},
            "B-K2": {"active": False, "changedAt": "2026-09-16T10:00:00Z"},
            "B-K3": {"active": True, "changedAt": "2026-09-16T10:00:00Z"},
        },
        "coverage": {"complete": True, "pendingEvents": 0, "schemaErrors": 0},
        "freshness": {"connected": True, "caughtUp": True, "lag": 0},
    }


class FakeClient:
    def __init__(self, updates, current=None, fail_push=False):
        self.updates = list(updates)
        self.current = current or (self.updates[-1] if self.updates else fixture())
        self.pushed = []
        self.fail_push = fail_push

    def json_get(self, path, params=None):
        if path == "/updates":
            after = params["after"]
            return {"snapshots": [item for item in self.updates if item["revision"] > after]}
        return self.current

    def push(self, body):
        if self.fail_push:
            raise OSError("push failed")
        self.pushed.append(body)


class ProtocolTests(unittest.TestCase):
    def test_complete_snapshot_becomes_influx_line_protocol(self):
        line = snapshot_lines(fixture(), timestamp_ns=123)
        self.assertTrue(line.startswith("business,currency=USD "))
        self.assertIn("revision=7i", line)
        self.assertIn('quality="ACTUAL"', line)
        self.assertIn("integrity_percent=100.0", line)
        self.assertIn("stale_authorized=60.0", line)
        self.assertIn("stale_authorized_alert=1i", line)
        self.assertTrue(line.endswith(" 123"))

    def test_no_closures_is_not_rendered_as_zero_percent(self):
        line = snapshot_lines(fixture(k1=None), timestamp_ns=123)
        self.assertIn("integrity_percent=-1.0", line)
        self.assertIn('integrity_state="SIN MUESTRA"', line)
        self.assertIn("integrity_sample=0i", line)

    def test_invalid_quality_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_snapshot(fixture(quality="FRESH"))


class RecoveryTests(unittest.TestCase):
    def test_replays_revisions_and_persists_only_confirmed_push(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor.json"
            client = FakeClient([fixture(1), fixture(2), fixture(3)])
            adapter = LiveAdapter(client, path)
            self.assertEqual(adapter.cycle(), 3)
            self.assertEqual(adapter.state.cursor, 3)
            self.assertEqual(json.loads(path.read_text()), {"revision": 3})
            self.assertEqual(len(client.pushed), 3)
            restarted = LiveAdapter(FakeClient([fixture(1), fixture(2), fixture(3), fixture(4)]), path)
            restarted.cycle()
            self.assertEqual(restarted.state.cursor, 4)

    def test_failed_push_does_not_advance_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor.json"
            adapter = LiveAdapter(FakeClient([fixture(1)], fail_push=True), path)
            with self.assertRaises(GrafanaPushError):
                adapter.cycle()
            self.assertEqual(adapter.state.cursor, 0)
            self.assertFalse(path.exists())

    def test_push_failure_keeps_source_health_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = LiveAdapter(FakeClient([fixture(1)], fail_push=True), Path(directory) / "cursor.json")
            with self.assertRaises(GrafanaPushError) as caught:
                adapter.cycle()
            adapter.fail(caught.exception)
            self.assertTrue(adapter.state.analytics_ok)
            self.assertFalse(adapter.state.grafana_ok)

    def test_idle_cycle_publishes_full_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor.json"
            path.write_text('{"revision": 7}')
            client = FakeClient([], current=fixture(7))
            adapter = LiveAdapter(client, path, AdapterState(cursor=7))
            adapter.cycle()
            self.assertEqual(len(client.pushed), 1)

    def test_gap_is_counted_and_repaired_by_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = LiveAdapter(FakeClient([fixture(3)]), Path(directory) / "cursor.json", AdapterState(cursor=1))
            adapter.cycle()
            self.assertEqual(adapter.state.cursor, 3)
            self.assertEqual(adapter.state.recovered_gaps, 1)


if __name__ == "__main__":
    unittest.main()
