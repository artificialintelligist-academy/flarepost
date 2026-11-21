"""SQLite storage for Flarepost incidents and their timeline."""

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from flarepost.domain import EntryKind, Incident, Severity, Status, TimelineEntry

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
);

CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents (id),
    kind TEXT NOT NULL CHECK (kind IN ('created', 'status', 'severity', 'note')),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("FLAREPOST_DB", DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
        _add_entry(conn, cursor.lastrowid, EntryKind.CREATED, f"Incident opened as {severity}", now)
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


def list_incidents(
    conn: sqlite3.Connection,
    status: Status | None = None,
    service: str | None = None,
    severity: Severity | None = None,
    before_id: int | None = None,
    limit: int | None = None,
) -> list[Incident]:
    conditions: list[str] = []
    params: list[object] = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if service is not None:
        conditions.append("service = ?")
        params.append(service)
    if severity is not None:
        conditions.append("severity = ?")
        params.append(severity)
    if before_id is not None:
        conditions.append("id < ?")
        params.append(before_id)

    query = "SELECT * FROM incidents"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return [_to_incident(row) for row in conn.execute(query, params)]


def incident_ids_starting_with(
    conn: sqlite3.Connection, prefix: str, limit: int
) -> tuple[list[int], int]:
    """Ids whose digits start with prefix, newest first, and how many match in total."""
    pattern = f"{prefix}%"
    total = conn.execute(
        "SELECT COUNT(*) FROM incidents WHERE CAST(id AS TEXT) LIKE ?", (pattern,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id FROM incidents WHERE CAST(id AS TEXT) LIKE ? ORDER BY id DESC LIMIT ?",
        (pattern, limit),
    )
    return [row["id"] for row in rows], total


def update_incident(
    conn: sqlite3.Connection,
    incident_id: int,
    status: Status | None = None,
    severity: Severity | None = None,
) -> Incident | None:
    current = get_incident(conn, incident_id)
    if current is None:
        return None

    now = datetime.now(UTC)
    new_status = status or current.status
    new_severity = severity or current.severity
    with conn:
        conn.execute(
            "UPDATE incidents SET status = ?, severity = ?, updated_at = ? WHERE id = ?",
            (new_status, new_severity, now.isoformat(), incident_id),
        )
        if new_status != current.status:
            message = f"Status changed from {current.status} to {new_status}"
            _add_entry(conn, incident_id, EntryKind.STATUS, message, now)
        if new_severity != current.severity:
            message = f"Severity changed from {current.severity} to {new_severity}"
            _add_entry(conn, incident_id, EntryKind.SEVERITY, message, now)
    return get_incident(conn, incident_id)


def resolve_incident(conn: sqlite3.Connection, incident_id: int, summary: str) -> Incident | None:
    """Resolve an incident and record what fixed it, in a single transaction."""
    current = get_incident(conn, incident_id)
    if current is None:
        return None

    now = datetime.now(UTC)
    with conn:
        conn.execute(
            "UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?",
            (Status.RESOLVED, now.isoformat(), incident_id),
        )
        _add_entry(
            conn, incident_id, EntryKind.STATUS,
            f"Status changed from {current.status} to {Status.RESOLVED}", now,
        )
        _add_entry(conn, incident_id, EntryKind.NOTE, f"Resolution: {summary}", now)
    return get_incident(conn, incident_id)


def add_note(conn: sqlite3.Connection, incident_id: int, message: str) -> TimelineEntry:
    now = datetime.now(UTC)
    with conn:
        entry_id = _add_entry(conn, incident_id, EntryKind.NOTE, message, now)
    return TimelineEntry(
        id=entry_id,
        incident_id=incident_id,
        kind=EntryKind.NOTE,
        message=message,
        created_at=now,
    )


def get_timeline(conn: sqlite3.Connection, incident_id: int) -> list[TimelineEntry]:
    rows = conn.execute(
        "SELECT * FROM timeline WHERE incident_id = ? ORDER BY created_at, id",
        (incident_id,),
    )
    return [_to_entry(row) for row in rows]


def _add_entry(
    conn: sqlite3.Connection,
    incident_id: int,
    kind: EntryKind,
    message: str,
    now: datetime,
) -> int:
    cursor = conn.execute(
        "INSERT INTO timeline (incident_id, kind, message, created_at) VALUES (?, ?, ?, ?)",
        (incident_id, kind, message, now.isoformat()),
    )
    return cursor.lastrowid


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


def _to_entry(row: sqlite3.Row) -> TimelineEntry:
    return TimelineEntry(
        id=row["id"],
        incident_id=row["incident_id"],
        kind=EntryKind(row["kind"]),
        message=row["message"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )