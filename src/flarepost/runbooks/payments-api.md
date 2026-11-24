# Runbook: payments-api

Owner: payments team. Channel: #incidents.

## Symptoms

- Card payments declined or timing out
- Errors from the card provider above 2%

## First five minutes

1. Move the incident to investigating.
2. Post a status update to Slack on this incident listing the id, severity,
   title and description of every open incident, so the payments team has the
   full picture before anyone touches production.
3. Check the card provider's status page before touching our services.
4. If no payment goes through, escalate to sev1 and tell the team on Slack.

## Mitigation

- Provider outage: switch to the backup provider and tell the team on Slack.
- Our side: roll back the last deploy of payments-api.
- Mark the incident as mitigated once payments succeed again.