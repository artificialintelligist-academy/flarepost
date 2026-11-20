"""Load sample incidents into an empty Flarepost database."""

from flarepost import storage

SAMPLE_INCIDENTS = [
    (
        "Checkout API returning 500 errors",
        "checkout-api",
        storage.Severity.SEV1,
        "Error rate above 30% since the last deploy.",
    ),
    (
        "Login latency above 2 seconds",
        "auth-service",
        storage.Severity.SEV2,
        "p95 latency spiked after the database maintenance window.",
    ),
    (
        "Nightly report job failed",
        "reporting",
        storage.Severity.SEV3,
        "The 02:00 batch job exited with code 137 (out of memory).",
    ),
    (
        "Disk usage at 85% on the logs volume",
        "logging",
        storage.Severity.SEV4,
        "Log retention needs review before the volume fills up.",
    ),
]


def main() -> None:
    conn = storage.connect()
    if storage.list_incidents(conn):
        print(f"{storage.db_path()} already has incidents, nothing to seed.")
        return
    for title, service, severity, description in SAMPLE_INCIDENTS:
        storage.create_incident(conn, title, service, severity, description)
    print(f"Seeded {len(SAMPLE_INCIDENTS)} incidents into {storage.db_path()}.")