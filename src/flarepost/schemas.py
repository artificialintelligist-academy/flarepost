"""Validated tool inputs. Each type also becomes part of the JSON Schema the model sees."""

from typing import Annotated

from pydantic import Field, StringConstraints

Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=120),
    Field(description="Short summary of what is broken, e.g. 'Checkout API returning 500 errors'."),
]
Service = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{1,62}$"),
    Field(description="Affected service as a lowercase slug, e.g. 'checkout-api'."),
]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=2000),
    Field(description="What is happening, the impact and anything already tried."),
]
IncidentId = Annotated[
    int,
    Field(ge=1, description="Numeric id of the incident, e.g. 3."),
]
NoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=2000),
    Field(description="What was found or done, e.g. 'Rolled back the last deploy.'"),
]
SlackText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=1000),
    Field(description="The update for the team, e.g. 'Rolled back the deploy, error rate is back to normal.'"),
]
ResolutionSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=1000),
    Field(description="What fixed the incident, in one or two sentences."),
]
DraftId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    Field(description="The draft_id returned by draft_status_update, e.g. 'drf_Q2x9...'."),
]