"""Bridge durable business snapshots to Grafana Live.

The analytics API owns calculation and history.  This process only validates
complete snapshots, resumes after its last confirmed revision and translates
them to the InfluxDB line protocol accepted by Grafana Live.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOG = logging.getLogger("grafana-live-adapter")
ALLOWED_QUALITY = {"ACTUAL", "INCOMPLETO", "DESACTUALIZADO"}


class GrafanaPushError(RuntimeError):
    """The source was reachable, but Grafana did not confirm the Live push."""


def _escape_measurement(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,")


def _escape_tag(value: str) -> str:
    return _escape_measurement(value).replace("=", "\\=")


def _field(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}i"
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError("non-finite number cannot be published")
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _money(kpi: dict[str, Any], currency: str) -> float:
    value = kpi.get("value", {})
    if not isinstance(value, dict):
        raise ValueError("money KPI value must be grouped by currency")
    return float(value.get(currency, 0))


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schemaVersion") != 1:
        raise ValueError("unsupported snapshot schema")
    revision = snapshot.get("revision")
    if type(revision) is not int or revision < 1:
        raise ValueError("snapshot revision must be a positive integer")
    quality = snapshot.get("quality")
    if quality not in ALLOWED_QUALITY:
        raise ValueError("unknown snapshot quality")
    if not isinstance(snapshot.get("generatedAt"), str):
        raise ValueError("generatedAt is required")
    kpis = snapshot.get("kpis")
    if not isinstance(kpis, dict) or any(name not in kpis for name in ("B-K1", "B-K2", "B-K3")):
        raise ValueError("B-K1, B-K2 and B-K3 are required")


def snapshot_lines(snapshot: dict[str, Any], timestamp_ns: int | None = None) -> str:
    """Return one complete Live row per currency."""
    validate_snapshot(snapshot)
    kpis = snapshot["kpis"]
    currencies = set(kpis["B-K2"].get("value", {})) | set(kpis["B-K3"].get("value", {}))
    currencies = sorted(currencies or {"USD"})
    coverage = snapshot.get("coverage", {})
    freshness = snapshot.get("freshness", {})
    alerts = snapshot.get("alerts", {})
    event_id = snapshot.get("lastEventId") or "bootstrap"
    correlation_id = snapshot.get("correlationId") or event_id
    timestamp_ns = timestamp_ns or time.time_ns()
    lines = []
    for currency in currencies:
        fields = {
            "revision": snapshot["revision"],
            "data_revision": int(snapshot.get("dataRevision", 0)),
            "generated_at": snapshot["generatedAt"],
            "source_event_id": event_id,
            "correlation_id": correlation_id,
            "quality": snapshot["quality"],
            "source": "business-analytics",
            "valid": bool(snapshot.get("valid", False)),
            "complete": bool(coverage.get("complete", False)),
            "pending_events": int(coverage.get("pendingEvents", 0)),
            "schema_errors": int(coverage.get("schemaErrors", 0)),
            "connected": bool(freshness.get("connected", False)),
            "caught_up": bool(freshness.get("caughtUp", False)),
            "lag": int(freshness.get("lag") or 0),
            "technical_health": int(bool(freshness.get("connected", False)) and bool(freshness.get("caughtUp", False))),
            "integrity_percent": float(kpis["B-K1"]["value"]) if kpis["B-K1"].get("value") is not None else -1.0,
            "integrity_sample": int(kpis["B-K1"].get("sample", 0)),
            "integrity_state": kpis["B-K1"].get("state", "SIN MUESTRA"),
            "closure_gap": _money(kpis["B-K2"], currency),
            "closure_gap_sample": int(kpis["B-K2"].get("sample", 0)),
            "closure_gap_state": kpis["B-K2"].get("state", "SIN MUESTRA"),
            "stale_authorized": _money(kpis["B-K3"], currency),
            "stale_authorized_sample": int(kpis["B-K3"].get("sample", 0)),
            "stale_authorized_state": kpis["B-K3"].get("state", "SIN MUESTRA"),
        }
        for name, prefix in (("B-K1", "integrity"), ("B-K2", "closure_gap"), ("B-K3", "stale_authorized")):
            active = alerts.get(name, {}).get("active")
            fields[f"{prefix}_alert"] = -1 if active is None else int(bool(active))
            fields[f"{prefix}_changed_at"] = alerts.get(name, {}).get("changedAt") or "unknown"
        encoded = ",".join(f"{key}={_field(value)}" for key, value in fields.items())
        lines.append(f"{_escape_measurement('business')},currency={_escape_tag(currency)} {encoded} {timestamp_ns}")
    return "\n".join(lines)


class HttpClient:
    def __init__(self, analytics_url: str, grafana_url: str, user: str, password: str, timeout: float = 2.0):
        self.analytics_url = analytics_url.rstrip("/")
        self.grafana_url = grafana_url.rstrip("/")
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.timeout = timeout

    def json_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{self.analytics_url}{path}{query}", headers={"Accept": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def push(self, body: str) -> None:
        request = Request(
            f"{self.grafana_url}/api/live/push/bankpulse",
            data=body.encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {self.auth}",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            if not 200 <= response.status < 300:
                raise HTTPError(request.full_url, response.status, "Grafana Live push failed", response.headers, None)


@dataclass
class AdapterState:
    cursor: int = 0
    analytics_ok: bool = False
    grafana_ok: bool = False
    last_push_at: float | None = None
    last_error: str | None = None
    recovered_gaps: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def public(self) -> dict[str, Any]:
        with self.lock:
            healthy = self.analytics_ok and self.grafana_ok and self.last_push_at is not None and time.time() - self.last_push_at < 3
            return {
                "status": "UP" if healthy else "DEGRADED",
                "cursor": self.cursor,
                "analytics": "UP" if self.analytics_ok else "DOWN",
                "grafanaLive": "UP" if self.grafana_ok else "DOWN",
                "lastPushAt": self.last_push_at,
                "lastError": self.last_error,
                "recoveredGaps": self.recovered_gaps,
            }


class LiveAdapter:
    def __init__(self, client: HttpClient, cursor_path: Path, state: AdapterState | None = None):
        self.client = client
        self.cursor_path = cursor_path
        self.state = state or AdapterState(cursor=self._load_cursor())

    def _load_cursor(self) -> int:
        try:
            value = json.loads(self.cursor_path.read_text())["revision"]
            return value if type(value) is int and value >= 0 else 0
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def _save_cursor(self, revision: int) -> None:
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.cursor_path.parent, prefix="cursor-")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump({"revision": revision}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.cursor_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def publish(self, snapshot: dict[str, Any]) -> None:
        revision = snapshot.get("revision")
        if type(revision) is not int or revision < self.state.cursor:
            return
        try:
            self.client.push(snapshot_lines(snapshot))
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            with self.state.lock:
                self.state.grafana_ok = False
            raise GrafanaPushError(str(error)) from error
        self._save_cursor(revision)
        with self.state.lock:
            self.state.cursor = revision
            self.state.analytics_ok = True
            self.state.grafana_ok = True
            self.state.last_push_at = time.time()
            self.state.last_error = None

    def cycle(self) -> int:
        """Publish all available revisions; return the number pushed."""
        cursor = self.state.cursor
        payload = self.client.json_get("/updates", {"after": cursor, "limit": 100})
        with self.state.lock:
            self.state.analytics_ok = True
        snapshots = payload.get("snapshots")
        if not isinstance(snapshots, list):
            raise ValueError("updates response does not contain snapshots")
        if not snapshots:
            # A full snapshot is also the bootstrap and idle heartbeat for newly opened panels.
            snapshot = self.client.json_get("/snapshot")
            revision = snapshot.get("revision", 0)
            if cursor and revision < cursor:
                raise ValueError("analytics revision moved backwards; preserve or reset the analytics volume")
            self.publish(snapshot)
            return 1
        expected = cursor + 1
        for snapshot in snapshots:
            revision = snapshot.get("revision")
            if type(revision) is not int:
                raise ValueError("update has no integer revision")
            if revision < expected:
                continue
            if revision > expected:
                # Every update is a complete snapshot, so the newer frame safely repairs the display.
                with self.state.lock:
                    self.state.recovered_gaps += revision - expected
            self.publish(snapshot)
            expected = revision + 1
        return len(snapshots)

    def fail(self, error: BaseException) -> None:
        with self.state.lock:
            if isinstance(error, GrafanaPushError):
                self.state.grafana_ok = False
            else:
                self.state.analytics_ok = False
            self.state.last_error = f"{type(error).__name__}: {str(error)[:180]}"


def serve_health(state: AdapterState, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/health", "/ready"):
                self.send_error(404)
                return
            result = state.public()
            body = json.dumps(result).encode()
            status = 200 if self.path == "/health" or result["status"] == "UP" else 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    client = HttpClient(
        os.getenv("ANALYTICS_URL", "http://business-analytics:8000"),
        os.getenv("GRAFANA_URL", "http://grafana:3000"),
        os.getenv("GRAFANA_USER", "admin"),
        os.environ["GRAFANA_PASSWORD"],
    )
    adapter = LiveAdapter(client, Path(os.getenv("CURSOR_PATH", "/data/cursor.json")))
    server = serve_health(adapter.state, int(os.getenv("PORT", "8080")))
    delay = 0.2
    try:
        while True:
            try:
                adapter.cycle()
                delay = 0.2
            except (GrafanaPushError, HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as error:
                adapter.fail(error)
                LOG.warning("Live bridge unavailable: %s", adapter.state.last_error)
                delay = min(2.0, delay * 2)
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
