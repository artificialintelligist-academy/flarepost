"""SQLite storage for Flarepost incidents."""

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".flarepost" / "flarepost.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    service TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('sev1', 'sev2', 'sev3', 'sev4')),
    status TEXT NOT NULL CHECK (status IN ('open', 'investigating', 'mitigated', 'resolved')),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class Severity(StrEnum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"


class Status(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class Incident:
    id: int
    title: str
    service: str
    severity: Severity
    status: Status
    description: str
    created_at: datetime
    updated_at: datetime


def db_path() -> Path:
    return Path(os.environ.get("FLAREPOST_DB", DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def create_incident(
    conn: sqlite3.Connection,
    title: str,
    service: str,
    severity: Severity,
    description: str = "",
) -> Incident:
    now = datetime.now(UTC)
    with conn:
        cursor = conn.execute(
            "INSERT INTO incidents "
            "(title, service, severity, status, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, service, severity, Status.OPEN, description, now.isoformat(), now.isoformat()),
        )
    return Incident(
        id=cursor.lastrowid,
        title=title,
        service=service,
        severity=severity,
        status=Status.OPEN,
        description=description,
        created_at=now,
        updated_at=now,
    )


def get_incident(conn: sqlite3.Connection, incident_id: int) -> Incident | None:
    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    return _to_incident(row) if row else None


def list_incidents(conn: sqlite3.Connection, status: Status | None = None) -> list[Incident]:
    query = "SELECT * FROM incidents"
    params: tuple[str, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    return [_to_incident(row) for row in conn.execute(query, params)]


def _to_incident(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        title=row["title"],
        service=row["service"],
        severity=Severity(row["severity"]),
        status=Status(row["status"]),
        description=row["description"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )