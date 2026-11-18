"""State-changing actions.

The system can help a student *do* things, not only answer questions. But an
assistant that writes to state without confirmation is a hazard, so the
protocol here is deliberately two-phase:

    propose -> preview -> student confirms or cancels -> commit

A pending action carries a preview describing exactly what will change, and
nothing is written until the student confirms with the matching token. The
student is the only actor with authority to commit; the assistant can only
ever propose.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .db import db
from .slots import AVAILABLE_SLOTS

#: Consultations can be booked up to 48 hours in advance.
MAX_ADVANCE_DAYS = 2

_WEEKDAYS = (
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday",
)

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_TIME_RE = re.compile(r"\b(\d{2}:\d{2})\b")


@dataclass
class ActionField:
    label: str
    value: str


@dataclass
class ProposedAction:
    """A state change that has been prepared but not carried out."""

    id: str
    kind: str
    status: str  # "awaiting-confirmation" | "committed" | "cancelled"
    title: str
    preview: str
    fields: list[ActionField]
    consequence: str
    reversible: bool
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "preview": self.preview,
            "fields": [asdict(f) for f in self.fields],
            "consequence": self.consequence,
            "reversible": self.reversible,
            "createdAt": self.created_at,
        }


@dataclass
class Booking:
    id: str
    slot_date: str
    slot_time: str
    topic: str
    status: str  # "confirmed" | "cancelled"
    booked_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slotDate": self.slot_date,
            "slotTime": self.slot_time,
            "topic": self.topic,
            "status": self.status,
            "bookedAt": self.booked_at,
        }


class ActionStore:
    """Action and booking store, persisted in SQLite.

    The store keeps the same interface as the previous JSON-backed version —
    ``propose``, ``commit``, ``cancel``, ``list_bookings`` — so the
    orchestrator and the API layer are unchanged. What changed is where the
    data lives: rows in the ``pending_actions`` and ``bookings`` tables
    rather than a file rewritten on every mutation.
    """

    def __init__(self, database=None, path: Path | None = None) -> None:
        # ``path`` is accepted for backwards compatibility with callers that
        # pointed the store at an isolated file. A path ending in ``.db`` is
        # used as a SQLite database; anything else is ignored, because the
        # old JSON format is no longer read.
        if database is None and path is not None and str(path).endswith(".db"):
            from .db import Database

            database = Database(path)
        self.database = database or db
        self.path = self.database.path

    # -- slots ---------------------------------------------------------- #

    def slot_available(self, slot_date: str, slot_time: str) -> bool:
        for booking in self.database.list_bookings():
            if (
                booking["status"] == "confirmed"
                and booking["slot_date"] == slot_date
                and booking["slot_time"] == slot_time
            ):
                return False
        return True

    def find_slots(
        self,
        slot_date: str | None = None,
        slot_time: str | None = None,
        free_text: str | None = None,
    ) -> list[dict]:
        """Match published slots against what the student asked for."""
        free = (free_text or "").lower()
        results = []

        for slot in self.database.list_slots():
            if slot_date and slot["date"] != slot_date:
                continue
            if slot_time and slot["time"] != slot_time:
                continue
            if free:
                weekday = date.fromisoformat(slot["date"]).strftime("%A").lower()
                if not re.search(rf"\b({_WEEKDAYS})\b", free) or weekday not in free:
                    continue
                hour = int(slot["time"][:2])
                if "morning" in free and hour >= 12:
                    continue
                if "afternoon" in free and hour < 12:
                    continue
                if "evening" in free and hour < 17:
                    continue
            results.append(
                {**slot, "free": self.slot_available(slot["date"], slot["time"])}
            )

        return results

    # -- proposals ------------------------------------------------------ #

    def propose(
        self,
        kind: str,
        fields: list[ActionField],
        title: str,
        preview: str,
        consequence: str,
        reversible: bool,
    ) -> ProposedAction:
        """Create a pending action. Nothing is written to the bookings yet."""
        action = ProposedAction(
            id=str(uuid.uuid4()),
            kind=kind,
            status="awaiting-confirmation",
            title=title,
            preview=preview,
            fields=fields,
            consequence=consequence,
            reversible=reversible,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.database.insert_action(action.to_dict())
        return action

    def propose_booking(self, slot: dict[str, str], topic: str) -> ProposedAction:
        return self.propose(
            kind="book_consultation",
            fields=[
                ActionField("Date", format_slot_date(slot["date"])),
                ActionField("Time", f"{slot['time']}–{add_minutes(slot['time'], 20)}"),
                ActionField("With", slot["tutor"]),
                ActionField("Topic", topic),
                ActionField("Length", "20 minutes"),
            ],
            title="Book a consultation slot",
            preview=(
                f"Book a 20-minute consultation with {slot['tutor']} on "
                f'{format_slot_date(slot["date"])} at {slot["time"]}, about "{topic}".'
            ),
            consequence=(
                "This slot will be taken in your name and a confirmation email will "
                "be sent. It can be cancelled later, but cancellations must be made "
                "at least 12 hours before the slot starts."
            ),
            reversible=True,
        )

    def propose_cancellation(self, booking: Booking) -> ProposedAction:
        return self.propose(
            kind="cancel_consultation",
            fields=[
                ActionField("Booking", booking.id[:8]),
                ActionField("Date", format_slot_date(booking.slot_date)),
                ActionField("Time", booking.slot_time),
                ActionField("Topic", booking.topic),
            ],
            title="Cancel a consultation booking",
            preview=(
                f'Cancel your consultation on {format_slot_date(booking.slot_date)} at '
                f'{booking.slot_time} about "{booking.topic}".'
            ),
            consequence=(
                "The slot will be released back to the pool and, if you are on the "
                "waiting list, offered to the next student. Cancelling within 12 "
                "hours of the slot is recorded as missed."
            ),
            reversible=False,
        )

    # -- commit / cancel ------------------------------------------------ #

    def commit(self, action_id: str) -> tuple[ProposedAction | None, Booking | None, str | None]:
        """Commit a pending action.

        Requires the exact action id, which the client only received as part
        of the preview — so confirmation cannot be forged by a stale or
        hallucinated reference.
        """
        record = self.database.get_action(action_id)
        if record is None:
            return None, None, (
                "This action is no longer pending. It may have already been "
                "confirmed or cancelled."
            )
        if record["status"] != "awaiting-confirmation":
            return None, None, f"This action has already been {record['status']}."

        action = ProposedAction(
            id=record["id"],
            kind=record["kind"],
            status=record["status"],
            title=record["title"],
            preview=record["preview"],
            fields=[ActionField(**f) for f in record["fields"]],
            consequence=record["consequence"],
            reversible=record["reversible"],
            created_at=record["created_at"],
        )
        field = {f.label: f.value for f in action.fields}

        if action.kind == "book_consultation":
            iso_date = _to_iso_date(field.get("Date", ""))
            slot_time = field.get("Time", "").split("–")[0]
            if not iso_date or not slot_time:
                return None, None, (
                    "The proposed booking is missing a date or time. Nothing was booked."
                )
            if not self.slot_available(iso_date, slot_time):
                return None, None, "That slot has already been taken. Nothing was booked."

            booking = Booking(
                id=str(uuid.uuid4()),
                slot_date=iso_date,
                slot_time=slot_time,
                topic=field.get("Topic", "Consultation"),
                status="confirmed",
                booked_at=datetime.now().isoformat(timespec="seconds"),
            )
            self.database.insert_booking(
                booking.id, booking.slot_date, booking.slot_time, booking.topic
            )

        elif action.kind == "cancel_consultation":
            booking_id = field.get("Booking", "")
            target = next(
                (
                    b
                    for b in self.database.list_bookings()
                    if b["id"].startswith(booking_id)
                ),
                None,
            )
            if target is None:
                return None, None, "That booking could not be found. Nothing was cancelled."
            if target["status"] == "cancelled":
                return None, None, "That booking was already cancelled."
            self.database.update_booking_status(target["id"], "cancelled")
            booking = Booking(
                id=target["id"],
                slot_date=target["slot_date"],
                slot_time=target["slot_time"],
                topic=target["topic"],
                status="cancelled",
                booked_at=target["booked_at"],
            )
        else:
            return None, None, "Unknown action type."

        action.status = "committed"
        self.database.update_action_status(action.id, "committed")
        return action, booking, None

    def cancel(self, action_id: str) -> str | None:
        """Cancel a pending action without performing it."""
        record = self.database.get_action(action_id)
        if record is None:
            return "This action is no longer pending."
        self.database.update_action_status(action_id, "cancelled")
        return None

    def list_bookings(self) -> list[Booking]:
        return [
            Booking(
                id=b["id"],
                slot_date=b["slot_date"],
                slot_time=b["slot_time"],
                topic=b["topic"],
                status=b["status"],
                booked_at=b["booked_at"],
            )
            for b in self.database.list_bookings()
            if b["status"] == "confirmed"
        ]


# ---------------------------------------------------------------------- #
# Helpers                                                              #
# ---------------------------------------------------------------------- #


def format_slot_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%a %-d %B %Y")


def _to_iso_date(display: str) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", display)
    if match:
        return match.group(1)
    try:
        return datetime.strptime(display, "%a %d %B %Y").date().isoformat()
    except ValueError:
        return None


def add_minutes(time: str, minutes: int) -> str:
    hours, mins = (int(part) for part in time.split(":"))
    total = hours * 60 + mins + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def extract_slot_intent(question: str) -> dict[str, str | None]:
    """Pull a date/time, or a weekday and part of the day, out of the question."""
    lower = question.lower()
    free_parts: list[str] = []

    for day in ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"):
        if day in lower:
            free_parts.append(day)
    for part in ("morning", "afternoon", "evening"):
        if part in lower:
            free_parts.append(part)

    return {
        "date": _DATE_RE.search(question).group(1) if _DATE_RE.search(question) else None,
        "time": _TIME_RE.search(question).group(1) if _TIME_RE.search(question) else None,
        "free_text": " ".join(free_parts) if free_parts else None,
    }


def extract_topic(question: str) -> str:
    """Pull the topic the student wants to discuss out of the question."""
    for pattern in (r"\babout\s+(.+?)(?:[.?!]|$)", r"\bregarding\s+(.+?)(?:[.?!]|$)"):
        match = re.search(pattern, question, re.I)
        if match:
            return match.group(1).strip()
    return "Course consultation"
