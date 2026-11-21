"""Send incident updates to a Slack channel through an incoming webhook."""

import os

import httpx

WEBHOOK_ENV = "FLAREPOST_SLACK_WEBHOOK_URL"
TIMEOUT_SECONDS = 10


class SlackError(Exception):
    """A message could not be delivered. The text never includes the webhook URL."""


def webhook_url() -> str | None:
    """Return the configured webhook, or None if Slack is not set up."""
    return os.environ.get(WEBHOOK_ENV) or None


def post_message(text: str) -> None:
    url = webhook_url()
    if url is None:
        raise SlackError(f"Slack is not configured. Set {WEBHOOK_ENV} in the server environment.")
    try:
        response = httpx.post(url, json={"text": text}, timeout=TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        raise SlackError(f"Slack did not answer within {TIMEOUT_SECONDS} seconds.") from None
    except httpx.HTTPError:
        raise SlackError("Could not reach Slack.") from None
    if response.status_code != 200:
        raise SlackError(f"Slack rejected the message with status {response.status_code}: {response.text}.")