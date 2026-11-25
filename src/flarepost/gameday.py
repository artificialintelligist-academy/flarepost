"""Game Day: replay the same checkout outage on a running Flarepost and time how it is handled."""

import argparse
import logging
import os
import time
from datetime import datetime

import anyio
from mcp import Client

from flarepost.remote import remote

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
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
DONE = {"mitigated", "resolved"}
POLL_SECONDS = 2
TIMEOUT_SECONDS = 30 * 60


def main() -> None:
    # The MCP client talks HTTP through the httpx2 logger, which logs every
    # request at INFO. One poll every two seconds would bury the timeline.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Replay a scripted checkout outage on a running Flarepost.")
    parser.add_argument(
        "--interval", type=float, default=30, help="seconds between signals (default: 30)"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("FLAREPOST_URL", DEFAULT_URL),
        help="the Flarepost MCP endpoint (default: %(default)s)",
    )
    args = parser.parse_args()
    try:
        anyio.run(_play, args.url, args.interval)
    except KeyboardInterrupt:
        # Ctrl+C is how a player gives up, not an error.
        print("\nGame Day stopped.")


async def _play(url: str, interval: float) -> None:
    # Every change goes through the server's tools, so clients subscribed to
    # this incident are notified, just as if a person had made it.
    async with Client(remote(url)) as client:
        incident = await _call(
            client,
            "create_incident",
            {"title": TITLE, "service": SERVICE, "severity": "sev3", "description": DESCRIPTION},
        )
        print(f"Game Day started. Incident #{incident['id']}: {TITLE} ({SERVICE})")
        print("Handle it until it is mitigated. Press Ctrl+C to give up.\n")

        await _run(client, incident["id"], interval)

        print(f"\nGame Day scoreboard for incident #{incident['id']}")
        for label, value in (await scoreboard(client, incident["id"])).items():
            print(f"  {label:<24} {value}")


async def _run(client: Client, incident_id: int, interval: float) -> None:
    pending = list(SIGNALS)
    seen: set[int] = set()
    started = time.monotonic()
    next_signal = started + interval
    while time.monotonic() - started < TIMEOUT_SECONDS:
        if pending and time.monotonic() >= next_signal:
            await _call(client, "add_note", {"incident_id": incident_id, "message": pending.pop(0)})
            next_signal += interval
        incident = await _call(client, "get_incident", {"incident_id": incident_id})
        for entry in await _timeline(client, incident_id):
            if entry["id"] not in seen:
                seen.add(entry["id"])
                _show(incident, entry)
        if incident["status"] in DONE:
            return
        await anyio.sleep(POLL_SECONDS)
    print("\nTime is up, the incident was not mitigated.")


async def scoreboard(client: Client, incident_id: int) -> dict[str, str]:
    """How long the team took to reach each milestone, or 'missed'."""
    incident = await _call(client, "get_incident", {"incident_id": incident_id})
    timeline = await _timeline(client, incident_id)

    def first(matches) -> str:
        for entry in timeline:
            if matches(entry["message"]):
                return _elapsed(incident["created_at"], entry["created_at"])
        return "missed"

    return {
        "Started investigating": first(lambda m: m.endswith("to investigating")),
        "Escalated to sev1": first(lambda m: m.endswith("to sev1")),
        "Told the team on Slack": first(lambda m: m.startswith("Posted to Slack:")),
        "Mitigated": first(lambda m: m.endswith(("to mitigated", "to resolved"))),
    }


async def _call(client: Client, name: str, arguments: dict) -> dict:
    result = await client.call_tool(name, arguments)
    if result.is_error:
        raise SystemExit(f"{name} failed: {result.content[0].text}")
    return result.structured_content


async def _timeline(client: Client, incident_id: int) -> list[dict]:
    return (await _call(client, "get_timeline", {"incident_id": incident_id}))["result"]


def _show(incident: dict, entry: dict) -> None:
    from_world = entry["kind"] == "created" or entry["message"].startswith(WORLD_PREFIXES)
    who = "" if from_world else "[team] "
    print(f"  {_elapsed(incident['created_at'], entry['created_at'])}  {who}{entry['message']}")


def _elapsed(start: str, end: str) -> str:
    seconds = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"