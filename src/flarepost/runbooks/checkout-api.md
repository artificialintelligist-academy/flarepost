# Runbook: checkout-api

Owner: payments team. Channel: #incidents.

## Symptoms

- p95 latency of POST /checkout above 1 s
- Error rate on POST /checkout above 5%
- Card payments failing at checkout

## First five minutes

1. Move the incident to investigating.
2. Check whether checkout-api was deployed in the last 30 minutes.
   The deploy bot writes every deploy to the incident timeline.
3. If more than 20% of checkouts fail, escalate to sev1 and tell the team on Slack.

## Mitigation

- Recent deploy: roll back to the previous version. This fixes most checkout incidents.
- No recent deploy: check the health of payments-api and the database connection pool.
- Mark the incident as mitigated once the error rate stays below 1% for five minutes.

## Afterwards

- Resolve the incident and write the postmortem from its timeline.