"""What Flarepost works with: incidents, their severity and status, and the timeline."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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


class EntryKind(StrEnum):
    CREATED = "created"
    STATUS = "status"
    SEVERITY = "severity"
    NOTE = "note"


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


@dataclass(frozen=True)
class TimelineEntry:
    id: int
    incident_id: int
    kind: EntryKind
    message: str
    created_at: datetime


@dataclass(frozen=True)
class IncidentPage:
    incidents: list[Incident]
    next_cursor: str | None


@dataclass(frozen=True)
class UpdatedIncident:
    incident: Incident
    updated: bool
    reason: str | None = None


@dataclass(frozen=True)
class ResolvedIncident:
    incident: Incident
    resolved: bool
    resolution: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class StatusUpdateDraft:
    draft_id: str
    incident_id: int
    message: str
    expires_at: datetime