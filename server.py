#!/usr/bin/env python3
"""Small SQLite-backed server for the checklist page."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "checklist.sqlite3"
HOST = "127.0.0.1"
PORT = 8000


def initialize_database() -> None:
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS checklist_state (
                task_key TEXT PRIMARY KEY,
                completed INTEGER NOT NULL CHECK (completed IN (0, 1)),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def read_states() -> dict[str, bool]:
    with sqlite3.connect(DATABASE) as connection:
        rows = connection.execute(
            "SELECT task_key, completed FROM checklist_state ORDER BY task_key"
        ).fetchall()
    return {task_key: bool(completed) for task_key, completed in rows}


def save_state(task_key: str, completed: bool) -> None:
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            """
            INSERT INTO checklist_state (task_key, completed, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(task_key) DO UPDATE SET
                completed = excluded.completed,
                updated_at = CURRENT_TIMESTAMP
            """,
            (task_key, int(completed)),
        )
        connection.commit()


class ChecklistHandler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json({"ok": True})
            return
        if path == "/api/state":
            self.send_json({"states": read_states()})
            return
        if path in {"/", "/spec-checklist.html"}:
            self.serve_file(ROOT / "spec-checklist.html")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        prefix = "/api/state/"
        if not path.startswith(prefix) or not path[len(prefix) :]:
            self.send_json({"error": "Expected /api/state/<task-key>"}, HTTPStatus.NOT_FOUND)
            return

        task_key = unquote(path[len(prefix) :])
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            completed = payload["completed"]
            if not isinstance(completed, bool):
                raise ValueError("completed must be a boolean")
        except (ValueError, KeyError, json.JSONDecodeError):
            self.send_json({"error": "Body must be JSON: {\"completed\": true|false}"}, HTTPStatus.BAD_REQUEST)
            return

        save_state(task_key, completed)
        self.send_json({"task_key": task_key, "completed": completed})

    def serve_file(self, file_path: Path) -> None:
        if not file_path.is_file() or file_path.parent != ROOT:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(file_path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), ChecklistHandler)
    print(f"Checklist server: http://{HOST}:{PORT}/")
    print(f"SQLite database: {DATABASE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
