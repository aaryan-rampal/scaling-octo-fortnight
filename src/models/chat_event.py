"""The shared conversational-message model produced by chat adaptors.

:class:`ChatEvent` is the Pydantic v2 analogue of the frozen
:class:`recall.schema.Event` dataclass. Source adaptors (iMessage, LLM chats)
parse messy, untrusted export data into this shape *before* it is handed to the
canonical store. Pydantic is used at this parse-time boundary on purpose: the
export JSON we ingest is external and irregular, so we want strict field
validation (required fields really required, timestamps coerced to tz-aware
datetimes) to fail loudly on malformed input rather than silently persisting a
half-formed row. Once validated, a ``ChatEvent`` carries exactly the columns the
``events`` table stores.

LLM-chat rows are a sibling of iMessage rows: they share every field and differ
only in the ``source`` discriminator (LLM rows set ``source="claude"``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChatEvent(BaseModel):
    """A single validated conversational message, ready for the canonical store.

    This mirrors :class:`recall.schema.Event` field-for-field. The dataclass is
    the *storage* form (frozen, plain dict round-trip); this model is the
    *parse* form that adaptors emit after validating external export data.

    Attributes:
        id: Stable hash identifying this event (16-char SHA-256 hex prefix).
        t_utc: Timezone-aware UTC timestamp of the message.
        author_role: ``"self"`` if authored by the account owner, else
            ``"other"``.
        content: Plain-text, privacy-filtered message body.
        thread_id: Identifier of the conversation the event belongs to.
        reply_to: ``id`` of the message this one replies to, or ``None`` for a
            thread root.
        raw_ref: Reference back to the source row (e.g.
            ``"claude:<conversation>#<message>"``).
        source: Originating system (e.g. ``"imessage"`` or ``"claude"``).
    """

    id: str
    t_utc: datetime
    author_role: str
    content: str
    thread_id: str
    reply_to: str | None
    raw_ref: str
    source: str
