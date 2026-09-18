from __future__ import annotations

import json
import mimetypes
import os
import queue
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from incidentzero.agent.controller import AgentController
from incidentzero.approval.gateway import ApprovalGateway
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.environment.topology import SERVICE_GRAPH, upstream_of
from incidentzero.model.groq_client import GroqModelClient
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry


# Global state for interactive live runs
class WebApprovalGateway:
    """Approval gateway that bridges to the web UI for interactive approval."""

    def __init__(self, run_state: dict[str, Any]) -> None:
        self.run_state = run_state
        self.response_event = threading.Event()
        self.decision: bool = True

    def approve(self, action_name: str, arguments: dict[str, Any], justification: str) -> bool:
        mode = self.run_state.get("approval_mode", "interactive")
        if mode == "auto":
            return True
        if mode == "deny":
            return False

        # Interactive: set pending approval and wait for web UI POST /api/approve
        self.response_event.clear()
        self.run_state["pending_approval"] = {
            "action": action_name,
            "arguments": arguments,
            "justification": justification,
            "timestamp": time.time(),
        }
        # Wait up to 60 seconds for human response from web UI
        signaled = self.response_event.wait(timeout=60.0)
        self.run_state["pending_approval"] = None
        if not signaled:
            return False  # Timed out -> default deny
        return self.decision


class LiveRunSession:
    def __init__(self, run_id: str, student_id: str, scenario: str, model: str, approval_mode: str) -> None:
        self.run_id = run_id
        self.student_id = student_id
        self.scenario = scenario
        self.model = model
        self.approval_mode = approval_mode
        self.status = "running"
        self.events: list[dict[str, Any]] = []
        self.outcome: dict[str, Any] | None = None
        self.error: str | None = None
        self.gateway = WebApprovalGateway(self.__dict__)
        self.pending_approval: dict[str, Any] | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            env = SimulationEnvironment(self.student_id, self.scenario)
            registry = ToolRegistry(env)
            trace_path = PROJECT_ROOT / "traces" / f"web_{self.student_id}_{self.scenario}.jsonl"

            class WebTraceRecorder(TraceRecorder):
                def __init__(self, path: Path, events_list: list[dict[str, Any]]) -> None:
                    super().__init__(path)
                    self.events_list = events_list

                def record(self, event: str, payload: dict[str, Any]) -> None:
                    super().record(event, payload)
                    item = {"ts": time.time(), "event": event, "payload": payload}
                    self.events_list.append(item)

            recorder = WebTraceRecorder(trace_path, self.events)

            # Record initial incident bootstrap in events
            incident_data = env.get_incident()
            recorder.record("bootstrap_incident", {"incident": incident_data})

            controller = AgentController(
                model=GroqModelClient(model=self.model),
                tools=registry,
                approval=self.gateway,
                budget=BudgetManager(),
                trace=recorder,
            )

            outcome = controller.run()
            self.outcome = asdict(outcome)
            self.status = "completed"
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)


RUN_SESSIONS: dict[str, LiveRunSession] = {}


class WebAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # ── API Endpoints ────────────────────────────────────────────────
        if path == "/api/config":
            self._handle_get_config()
            return
        if path == "/api/topology":
            self._handle_get_topology()
            return
        if path == "/api/traces":
            self._handle_get_traces()
            return
        if path == "/api/trace":
            file_param = query.get("file", [""])[0]
            self._handle_get_trace_file(file_param)
            return
        if path == "/api/run_status":
            run_id = query.get("run_id", [""])[0]
            self._handle_get_run_status(run_id)
            return

        # ── Static Files ────────────────────────────────────────────────
        static_dir = PROJECT_ROOT / "web"
        req_file = path.lstrip("/")
        if not req_file or req_file == "/":
            req_file = "index.html"

        file_path = (static_dir / req_file).resolve()
        if not str(file_path).startswith(str(static_dir)) or not file_path.is_file():
            self.send_error(404, "File not found")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.send_error(500, f"Error reading file: {exc}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(post_body) if post_body else {}
        except Exception:
            data = {}

        if path == "/api/run":
            self._handle_post_run(data)
            return
        if path == "/api/approve":
            self._handle_post_approve(data)
            return
        if path == "/api/save_config":
            self._handle_post_save_config(data)
            return

        self.send_error(404, "API endpoint not found")

    # ── Handlers ─────────────────────────────────────────────────────────

    def _handle_get_config(self) -> None:
        config_path = PROJECT_ROOT / "configs" / "services.json"
        services_data = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        self._send_json({
            "student_id": os.getenv("STUDENT_ID", "23I-0018"),
            "groq_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            "has_groq_key": bool(os.getenv("GROQ_API_KEY")),
            "available_models": [
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
                "qwen/qwen3.8-27b",
            ],
            "available_scenarios": ["public-a", "public-b"],
            "services": services_data.get("services", []),
            "critical_path": services_data.get("critical_path", []),
        })

    def _handle_get_topology(self) -> None:
        config_path = PROJECT_ROOT / "configs" / "services.json"
        services_data = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        critical = set(services_data.get("critical_path", []))

        nodes = []
        for name in services_data.get("services", []):
            nodes.append({
                "id": name,
                "label": name,
                "is_critical": name in critical,
                "downstream": SERVICE_GRAPH.get(name, []),
                "upstream": upstream_of(name),
            })

        edges = []
        for src, targets in SERVICE_GRAPH.items():
            for tgt in targets:
                edges.append({"source": src, "target": tgt})

        self._send_json({"nodes": nodes, "edges": edges, "service_graph": SERVICE_GRAPH})

    def _handle_get_traces(self) -> None:
        traces_dir = PROJECT_ROOT / "traces"
        files_info = []
        if traces_dir.exists():
            for file_path in sorted(traces_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True):
                files_info.append({
                    "name": file_path.name,
                    "size_bytes": file_path.stat().st_size,
                    "modified_time": file_path.stat().st_mtime,
                })
        self._send_json({"traces": files_info})

    def _handle_get_trace_file(self, filename: str) -> None:
        if not filename:
            self._send_json({"error": "Missing 'file' parameter"}, 400)
            return
        safe_name = Path(filename).name
        trace_file = PROJECT_ROOT / "traces" / safe_name
        if not trace_file.is_file():
            self._send_json({"error": "Trace file not found"}, 404)
            return

        events = []
        try:
            for line in trace_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
            self._send_json({"filename": safe_name, "total_events": len(events), "events": events})
        except Exception as exc:
            self._send_json({"error": f"Failed parsing trace: {exc}"}, 500)

    def _handle_post_run(self, data: dict[str, Any]) -> None:
        student_id = data.get("student_id") or os.getenv("STUDENT_ID", "23I-0018")
        scenario = data.get("scenario", "public-a")
        model = data.get("model") or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        approval_mode = data.get("approval_mode", "interactive")

        run_id = f"run_{int(time.time())}_{student_id}_{scenario}"
        session = LiveRunSession(run_id, student_id, scenario, model, approval_mode)
        RUN_SESSIONS[run_id] = session
        session.start()

        self._send_json({"run_id": run_id, "status": "started", "message": f"Execution started for {scenario}"})

    def _handle_get_run_status(self, run_id: str) -> None:
        session = RUN_SESSIONS.get(run_id)
        if not session:
            self._send_json({"error": "Run session not found"}, 404)
            return

        self._send_json({
            "run_id": session.run_id,
            "status": session.status,
            "events_count": len(session.events),
            "events": session.events,
            "pending_approval": session.pending_approval,
            "outcome": session.outcome,
            "error": session.error,
        })

    def _handle_post_approve(self, data: dict[str, Any]) -> None:
        run_id = data.get("run_id")
        approved = bool(data.get("approved", True))

        session = RUN_SESSIONS.get(run_id)
        if not session or not session.pending_approval:
            self._send_json({"error": "No pending approval for this run"}, 400)
            return

        session.gateway.decision = approved
        session.gateway.response_event.set()
        self._send_json({"status": "ok", "decision": "approved" if approved else "denied"})

    def _handle_post_save_config(self, data: dict[str, Any]) -> None:
        env_path = PROJECT_ROOT / ".env"
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updates = {}
        if "groq_model" in data:
            updates["GROQ_MODEL"] = data["groq_model"]
        if "student_id" in data:
            updates["STUDENT_ID"] = data["student_id"]
        if "groq_api_key" in data and data["groq_api_key"]:
            updates["GROQ_API_KEY"] = data["groq_api_key"]

        new_lines = []
        seen = set()
        for line in lines:
            if "=" in line and not line.strip().startswith("#"):
                k, _ = line.split("=", 1)
                k = k.strip()
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}")
                    seen.add(k)
                    continue
            new_lines.append(line)

        for k, v in updates.items():
            if k not in seen:
                new_lines.append(f"{k}={v}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        for k, v in updates.items():
            os.environ[k] = v

        self._send_json({"status": "ok", "updated": updates})


def run_server(port: int = 8765) -> None:
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, WebAppHandler)
    print(f"IncidentZero Web Visualizer running on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server...")
        httpd.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run_server(port)
