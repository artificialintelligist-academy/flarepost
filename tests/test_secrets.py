"""Secrets never reach the logs: anyone who reads them could use the webhook."""

import logging

import httpx

from flarepost.integrations import slack

SECRET_URL = "https://hooks.slack.com/services/T000/B000/not-a-real-secret"


def test_the_webhook_url_never_reaches_the_logs(monkeypatch, caplog):
    def post(url, **kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    monkeypatch.setenv(slack.WEBHOOK_ENV, SECRET_URL)
    monkeypatch.setattr(httpx, "post", post)
    caplog.set_level(logging.INFO)

    slack.post_message("Rolling back the deploy.")

    assert "not-a-real-secret" not in caplog.text