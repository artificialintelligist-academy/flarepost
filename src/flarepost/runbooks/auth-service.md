# Runbook: auth-service

Owner: identity team. Channel: #incidents.

## Symptoms

- Login p95 latency above 2 s
- Spike of failed logins with valid credentials

## First five minutes

1. Move the incident to investigating.
2. Check for recent database maintenance or a new deploy of auth-service.
3. If nobody can log in, escalate to sev1 and tell the team on Slack.

## Mitigation

- Slow queries after maintenance: rebuild the sessions index.
- Recent deploy: roll back to the previous version.
- Mark the incident as mitigated once login latency is below 500 ms.