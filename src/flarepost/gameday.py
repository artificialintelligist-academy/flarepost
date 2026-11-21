"""Game Day: replay the same checkout outage and time how it is handled."""

import argparse
import time
from contextlib import closing
from datetime import datetime

from flarepost import storage
from flarepost.domain import EntryKind, Incident, Severity, Status, TimelineEntry

TITLE = "Checkout latency rising"
SERVICE = "checkout-api"
DESCRIPTION = "Raised automatically by the checkout latency alert."
SIGNALS = [
    "[monitor] Checkout p95 latency at 4.2 s, the threshold is 1 s.",
    "[monitor] Error rate on POST /checkout at 12%.",
    "[deploy-bot] checkout-api v2.31.0 went out 6 minutes before the first alert.",
    "[monitor] Error rate at 35%. Most card payments are failing.",
]
WORLD_PREFIXES = ("[monitor]", "[deploy-bot]")
DONE = {Status.MITIGATED, Status.RESOLVED}
POLL_SECONDS = 2
TIMEOUT_SECONDS = 30 * 60


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a scripted checkout outage.")
    parser.add_argument(
        "--interval", type=float, default=30, help="seconds between signals (default: 30)"
    )
    args = parser.parse_args()

    with closing(storage.connect()) as conn:
        incident = storage.create_incident(conn, TITLE, SERVICE, Severity.SEV3, DESCRIPTION)
    print(f"Game Day started. Incident #{incident.id}: {TITLE} ({SERVICE})")
    print("Handle it until it is mitigated. Press Ctrl+C to give up.\n")

    _run(incident.id, args.interval)
    _print_scoreboard(incident.id)


def _run(incident_id: int, interval: float) -> None:
    pending = list(SIGNALS)
    seen: set[int] = set()
    started = time.monotonic()
    next_signal = started + interval
    while time.monotonic() - started < TIMEOUT_SECONDS:
        with closing(storage.connect()) as conn:
            if pending and time.monotonic() >= next_signal:
                storage.add_note(conn, incident_id, pending.pop(0))
                next_signal += interval
            incident = storage.get_incident(conn, incident_id)
            for entry in storage.get_timeline(conn, incident_id):
                if entry.id not in seen:
                    seen.add(entry.id)
                    _show(incident, entry)
            if incident.status in DONE:
                return
        time.sleep(POLL_SECONDS)
    print("\nTime is up, the incident was not mitigated.")


def _show(incident: Incident, entry: TimelineEntry) -> None:
    from_world = entry.kind is EntryKind.CREATED or entry.message.startswith(WORLD_PREFIXES)
    who = "" if from_world else "[team] "
    print(f"  {_elapsed(incident.created_at, entry.created_at)}  {who}{entry.message}")


def _print_scoreboard(incident_id: int) -> None:
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
        timeline = storage.get_timeline(conn, incident_id)

    def first(matches) -> str:
        for entry in timeline:
            if matches(entry):
                return _elapsed(incident.created_at, entry.created_at)
        return "missed"

    rows = {
        "Started investigating": first(lambda e: e.message.endswith("to investigating")),
        "Escalated to sev1": first(lambda e: e.message.endswith("to sev1")),
        "Told the team on Slack": first(lambda e: e.message.startswith("Posted to Slack:")),
        "Mitigated": first(lambda e: e.message.endswith(("to mitigated", "to resolved"))),
    }
    print(f"\nGame Day scoreboard for incident #{incident_id}")
    for label, value in rows.items():
        print(f"  {label:<24} {value}")


def _elapsed(start: datetime, end: datetime) -> str:
    minutes, seconds = divmod(int((end - start).total_seconds()), 60)
    return f"{minutes:02d}:{seconds:02d}"