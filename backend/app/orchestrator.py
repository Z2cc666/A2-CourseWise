"""Orchestration: turn a student question into an evidence-backed response.

Pipeline
    1. Intent detection — is this a question, or a request to change state?
    2. Retrieval — BM25 over the corpus, with qualified-name phrase matching.
    3. Freshness and conflict analysis of the retrieved evidence.
    4. Sufficiency check — may we answer at all?
    5. Generation — answer, or refuse.
    6. Action proposal — for state-changing requests, propose a preview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .actions import (
    ActionStore,
    extract_slot_intent,
    extract_topic,
    format_slot_date,
)
from .corpus import CORPUS, CourseDoc
from .generation import ExtractiveGenerator, GenerationInput, create_generator
from .policy import (
    Conflict,
    EvidenceItem,
    Warning,
    assess_sufficiency,
    build_evidence,
    corpus_today,
    current_version_of,
    detect_conflicts,
    format_date,
    versions_of,
)
from .retrieval import retrieve

#: Patterns that suggest the student is asking for something to be *done*.
ACTION_PATTERNS = (
    re.compile(r"\bbook\b", re.I),
    re.compile(r"\breserve\b", re.I),
    re.compile(r"\bsign\s?up\b", re.I),
    re.compile(r"\bschedule\b", re.I),
    re.compile(r"\bcancel\b", re.I),
    re.compile(r"\bunbook\b", re.I),
)

RELATED_BY_KIND = {
    "assessment": lambda e: f"What is the deadline and weighting for {e.title}?",
    "policy": lambda e: "What happens if I use AI in assessed work?",
    "schedule": lambda e: "What does the Week 3 timeline cover?",
    "module-info": lambda e: "How do I book a consultation slot?",
    "resource": lambda e: "Which reading should I use for trust and transparency?",
    "faq": lambda e: "What file format should I submit?",
}

FALLBACK_QUESTIONS = (
    "When is the Assignment 1 deadline?",
    "What is the final exam format?",
    "Can I use AI in my assignment?",
)


@dataclass
class SourceCard:
    id: str
    title: str
    kind: str
    owner: str
    updated_at: str
    updated_at_label: str
    section: str
    excerpt: str
    source_url: str | None
    relevance: float
    freshness: dict
    cited: bool

    @property
    def freshness_state(self) -> str:
        """The freshness state as a plain string, e.g. 'superseded'."""
        return self.freshness.get("freshness", "current")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "owner": self.owner,
            "updatedAt": self.updated_at,
            "updatedAtLabel": self.updated_at_label,
            "section": self.section,
            "excerpt": self.excerpt,
            "sourceUrl": self.source_url,
            "relevance": self.relevance,
            "freshness": self.freshness,
            "cited": self.cited,
        }


@dataclass
class AnswerResponse:
    status: str
    answer: str
    verdict: dict
    sources: list[SourceCard] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    not_found: dict | None = None
    action: dict | None = None
    related_questions: list[str] = field(default_factory=list)
    backend: str = "extractive"
    model: str | None = None
    considered_documents: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "verdict": self.verdict,
            "sources": [s.to_dict() for s in self.sources],
            "warnings": [
                {
                    "id": w.id,
                    "severity": w.severity,
                    "title": w.title,
                    "detail": w.detail,
                    "evidenceIds": list(w.evidence_ids),
                }
                for w in self.warnings
            ],
            "notFound": self.not_found,
            "action": self.action,
            "relatedQuestions": self.related_questions,
            "backend": self.backend,
            "model": self.model,
            "consideredDocuments": self.considered_documents,
        }


def _normalise_heading(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


class Orchestrator:
    """Turns a question into an answer plus its evidence."""

    def __init__(self, store: ActionStore | None = None, generator=None) -> None:
        self.store = store or ActionStore()
        self.generator = generator or create_generator()
        self.today = corpus_today()

    # ------------------------------------------------------------------ #
    # Entry point                                                       #
    # ------------------------------------------------------------------ #

    async def handle(
        self,
        question: str,
        allow_action: bool = True,
        history: list[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        trimmed = question.strip()
        if not trimmed:
            return self._empty_response(
                'Ask a question about the course, for example "When is the Assignment '
                '1 deadline?"'
            )

        wants_action = allow_action and any(p.search(trimmed) for p in ACTION_PATTERNS)
        if wants_action:
            action_response = self._try_action(trimmed)
            if action_response is not None:
                return action_response

        return self._answer_question(trimmed, history or [])

    # ------------------------------------------------------------------ #
    # Question answering                                                #
    # ------------------------------------------------------------------ #

    def _answer_question(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> AnswerResponse:
        hits = retrieve(question, limit=10)
        evidence = build_evidence(hits, self.today)
        sufficiency = assess_sufficiency(question, hits)
        conflicts = detect_conflicts()

        warnings = self._build_warnings(evidence, conflicts)
        superseded = [e for e in evidence if e.freshness.freshness == "superseded"]

        # If retrieval found a superseded version, we must not lean on its
        # values. We answer from the version in force instead, and flag the
        # change to the student.
        answerable = self._prefer_current_versions(evidence)
        must_refuse = sufficiency.level == "insufficient" or not answerable

        generated = self.generator.generate(
            GenerationInput(
                question=question,
                evidence=answerable,
                must_refuse=must_refuse,
                refusal_reason=(
                    "I could not confirm this from the current course documents."
                    if sufficiency.level == "insufficient"
                    else None
                ),
                warnings=tuple(w.title for w in warnings),
                history=tuple(history or ()),
            )
        )

        cited_ids = set(generated.cited_passage_ids)
        max_score = max((e.score for e in answerable), default=0.001)

        sources: list[SourceCard] = [
            SourceCard(
                id=e.passage_id,
                title=e.title,
                kind=e.kind,
                owner=e.owner,
                updated_at=e.updated_at,
                updated_at_label=e.updated_at_label,
                section=e.heading,
                excerpt=e.text,
                source_url=e.source_url,
                relevance=round(min(1.0, e.score / max_score), 2),
                freshness={
                    "freshness": e.freshness.freshness,
                    "label": e.freshness.label,
                    "detail": e.freshness.detail,
                    **(
                        {
                            "supersededBy": {
                                "title": e.freshness.superseded_by[1],
                                "updatedAt": e.freshness.superseded_by[2],
                            }
                        }
                        if e.freshness.superseded_by
                        else {}
                    ),
                },
                cited=e.passage_id in cited_ids,
            )
            for e in answerable
        ]

        # Show the superseded passages that were retrieved too, so the student
        # can see what the old version said and why it was set aside.
        for e in superseded:
            if any(s.id == e.passage_id for s in sources):
                continue
            sources.append(
                SourceCard(
                    id=e.passage_id,
                    title=e.title,
                    kind=e.kind,
                    owner=e.owner,
                    updated_at=e.updated_at,
                    updated_at_label=e.updated_at_label,
                    section=e.heading,
                    excerpt=e.text,
                    source_url=e.source_url,
                    relevance=0.0,
                    freshness={
                        "freshness": e.freshness.freshness,
                        "label": e.freshness.label,
                        "detail": e.freshness.detail,
                        **(
                            {
                                "supersededBy": {
                                    "title": e.freshness.superseded_by[1],
                                    "updatedAt": e.freshness.superseded_by[2],
                                }
                            }
                            if e.freshness.superseded_by
                            else {}
                        ),
                    },
                    cited=False,
                )
            )

        if must_refuse:
            status = "insufficient-evidence"
        elif any(w.severity == "warning" for w in warnings):
            status = "answered-with-caveats"
        else:
            status = "answered"

        if sufficiency.level == "supported":
            verdict_label = "Supported by course documents"
            verdict_detail = (
                f"{len(answerable)} passage"
                f"{'s' if len(answerable) != 1 else ''} from the course "
                "documentation directly address this question."
            )
        elif sufficiency.level == "partial":
            verdict_label = "Partially supported"
            verdict_detail = (
                "The passages below are related but may not fully cover what you "
                "asked. Read the excerpts before relying on this answer."
            )
        else:
            verdict_label = "Not confirmed by course documents"
            verdict_detail = "No current course document covers this question, so no answer is given."

        return AnswerResponse(
            status=status,
            answer=generated.text,
            verdict={
                "label": verdict_label,
                "detail": verdict_detail,
                "confidence": sufficiency.confidence,
            },
            sources=sources,
            warnings=warnings,
            not_found=(
                {
                    "reason": sufficiency.reasons[0] if sufficiency.reasons else "",
                    "suggestions": list(sufficiency.next_steps),
                }
                if must_refuse
                else None
            ),
            related_questions=self._suggest_related(answerable, question),
            backend=generated.backend,
            model=generated.model,
            considered_documents=self._considered_docs(answerable),
        )

    def _prefer_current_versions(self, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
        """Swap superseded passages for the version in force.

        If retrieval only found an old version of a document, answering from it
        would propagate a value that no longer applies. Instead we locate the
        matching section in the current version and answer from that.
        """
        from .policy import assess_freshness

        out: list[EvidenceItem] = []
        seen: set[tuple[str, str]] = set()

        for item in evidence:
            if item.freshness.freshness not in ("superseded", "archived"):
                key = (item.doc_id, item.passage_id)
                if key not in seen:
                    seen.add(key)
                    out.append(item)
                continue

            current = current_version_of(item.doc_key)
            if current is None:
                key = (item.doc_id, item.passage_id)
                if key not in seen:
                    seen.add(key)
                    out.append(item)
                continue

            match = next(
                (
                    p
                    for p in current.passages
                    if _normalise_heading(p.heading) == _normalise_heading(item.heading)
                ),
                None,
            ) or current.passages[0]

            key = (current.id, match.id)
            if key in seen:
                continue
            seen.add(key)

            out.append(
                EvidenceItem(
                    doc_id=current.id,
                    doc_key=item.doc_key,
                    title=current.title,
                    kind=current.kind,
                    owner=current.owner,
                    updated_at=current.updated_at,
                    updated_at_label=format_date(current.updated_at),
                    summary=current.summary,
                    source_url=current.source_url,
                    passage_id=match.id,
                    heading=match.heading,
                    text=match.text,
                    score=item.score,
                    matched_terms=item.matched_terms,
                    matched_phrases=item.matched_phrases,
                    freshness=assess_freshness(current, self.today),
                )
            )

        return out

    # ------------------------------------------------------------------ #
    # Actions                                                           #
    # ------------------------------------------------------------------ #

    def _try_action(self, question: str) -> AnswerResponse | None:
        lower = question.lower()

        if re.search(r"\bcancel\b|\bunbook\b", lower):
            bookings = self.store.list_bookings()
            if not bookings:
                return self._actionless_response(
                    "You do not have any active bookings to cancel.",
                    "There is nothing in your bookings to cancel right now.",
                )

            intent = extract_slot_intent(question)
            target = (
                next((b for b in bookings if b.slot_date == intent["date"]), None)
                if intent["date"]
                else bookings[0]
            )
            if target is None:
                return self._actionless_response(
                    "I could not find a matching booking.",
                    f"You have {len(bookings)} active booking(s), but none matched "
                    "that date.",
                )

            action = self.store.propose_cancellation(target)
            return self._action_response(action, question)

        intent = extract_slot_intent(question)
        topic = extract_topic(question)
        matches = self.store.find_slots(
            slot_date=intent["date"],
            slot_time=intent["time"],
            free_text=intent["free_text"],
        )

        if not matches:
            return self._actionless_response(
                "I could not find a consultation slot matching that request.",
                "No published slot matches that date, time or day. Try asking for a "
                "specific date, or a weekday and part of the day.",
            )

        free = [m for m in matches if m["free"]]
        if not free:
            return self._actionless_response(
                "Every slot matching that request is already taken.",
                "Try a different day or time. You can also join the waiting list "
                "through the module portal.",
            )

        chosen = free[0]
        action = self.store.propose_booking(chosen, topic)
        return self._action_response(
            action,
            question,
            alternatives=[
                {"date": m["date"], "time": m["time"], "tutor": m["tutor"]}
                for m in free[1:4]
            ],
        )

    def _action_response(
        self,
        action,
        question: str,
        alternatives: list[dict] | None = None,
    ) -> AnswerResponse:
        warnings = [
            Warning(
                id="confirm-required",
                severity="caution",
                title="Nothing has been booked yet.",
                detail=(
                    "This is a preview of what would change. Confirm to go ahead, or "
                    "cancel to leave everything as it is."
                ),
                evidence_ids=(),
            )
        ]

        related = [
            f"Book {a['date']} at {a['time']} with {a['tutor']} instead"
            for a in (alternatives or [])
        ]
        related += ["What should I prepare for a consultation?", "How do I cancel a booking?"]

        return AnswerResponse(
            status="action-proposed",
            answer=action.preview,
            verdict={
                "label": "Awaiting your confirmation",
                "detail": "The system has prepared the change but has not carried it out.",
                "confidence": 1.0,
            },
            warnings=warnings,
            action=action.to_dict(),
            related_questions=related,
        )

    def _actionless_response(self, verdict_label: str, answer: str) -> AnswerResponse:
        """A response for an action request that could not be prepared.

        The status is ``action-unavailable``, not ``action-proposed``. The
        two are different promises: ``action-proposed`` means a confirmation
        card is waiting for the student, and it always carries an action.
        Reporting it here claimed a pending confirmation that did not
        exist, which is the one thing the two-phase protocol is meant to
        make impossible.
        """
        return AnswerResponse(
            status="action-unavailable",
            answer=answer,
            verdict={
                "label": verdict_label,
                "detail": "No change was made.",
                "confidence": 1.0,
            },
            related_questions=["Show me available consultation slots"],
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                           #
    # ------------------------------------------------------------------ #

    def _build_warnings(
        self, evidence: list[EvidenceItem], conflicts: list[Conflict]
    ) -> list[Warning]:
        warnings: list[Warning] = []
        seen: set[str] = set()

        def push(warning: Warning) -> None:
            if warning.id in seen:
                return
            seen.add(warning.id)
            warnings.append(warning)

        # Warn once per *document version* rather than once per passage: a
        # student needs to know that a document is out of date, not that three
        # of its paragraphs are. The key is the version id, not the document
        # key — grouping by document key would collapse the current version
        # and its superseded predecessor into one entry and hide the warning
        # about the old copy.
        by_doc: dict[str, EvidenceItem] = {}
        for item in evidence:
            existing = by_doc.get(item.doc_id)
            if existing is None or item.score > existing.score:
                by_doc[item.doc_id] = item

        titles = {
            "superseded": ("has a newer version.", "warning"),
            "expired": ("is past its validity date.", "warning"),
            "archived": ("has been withdrawn.", "warning"),
        }

        for item in by_doc.values():
            entry = titles.get(item.freshness.freshness)
            if entry is None:
                continue
            suffix, severity = entry
            push(
                Warning(
                    id=f"{item.freshness.freshness}-{item.doc_id}",
                    severity=severity,
                    title=f"{item.title} {suffix}",
                    detail=item.freshness.detail,
                    evidence_ids=tuple(
                        e.passage_id for e in evidence if e.doc_id == item.doc_id
                    ),
                )
            )

        # One warning per changed document, listing every value that changed.
        conflicts_by_doc: dict[str, list[Conflict]] = {}
        for conflict in conflicts:
            relevant = any(
                e.passage_id in (conflict.passage_id, conflict.counter_passage_id)
                for e in evidence
            )
            if not relevant:
                continue
            conflicts_by_doc.setdefault(conflict.doc_key, []).append(conflict)

        for doc_key, items in conflicts_by_doc.items():
            title = items[0].title
            push(
                Warning(
                    id=f"conflict-{doc_key}",
                    severity="caution",
                    title=(
                        f"A value in {title} changed between versions."
                        if len(items) == 1
                        else f"{len(items)} values in {title} changed between versions."
                    ),
                    detail=" ".join(c.detail for c in items),
                    evidence_ids=tuple(
                        dict.fromkeys(
                            pid
                            for c in items
                            for pid in (c.passage_id, c.counter_passage_id)
                        )
                    ),
                )
            )

        return warnings

    def _suggest_related(self, evidence: list[EvidenceItem], question: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        question_words = set(question.lower().split())

        for item in evidence:
            if len(out) >= 3:
                break
            builder = RELATED_BY_KIND.get(item.kind)
            if builder is None:
                continue
            suggestion = builder(item)
            if not suggestion or suggestion in seen:
                continue
            if any(
                w in suggestion.lower()
                for w in question_words
                if len(w) > 4 and w not in ("when", "does", "assignment")
            ):
                continue
            seen.add(suggestion)
            out.append(suggestion)

        for fallback in FALLBACK_QUESTIONS:
            if len(out) >= 3:
                break
            if fallback in seen:
                continue
            seen.add(fallback)
            out.append(fallback)

        return out

    def _considered_docs(self, evidence: list[EvidenceItem]) -> list[dict]:
        keys = list(dict.fromkeys(e.doc_key for e in evidence))
        documents = []
        for key in keys:
            latest = versions_of(key)[0]
            documents.append(
                {
                    "title": latest.title,
                    "updatedAtLabel": format_date(latest.updated_at),
                    "status": latest.status,
                }
            )
        return documents[:6]

    def _empty_response(self, hint: str) -> AnswerResponse:
        return AnswerResponse(
            status="insufficient-evidence",
            answer=hint,
            verdict={
                "label": "Nothing to go on",
                "detail": "No question was provided.",
                "confidence": 0.0,
            },
            not_found={"reason": "No question was provided.", "suggestions": [hint]},
            related_questions=list(FALLBACK_QUESTIONS),
        )


__all__ = ["Orchestrator", "AnswerResponse", "SourceCard", "ExtractiveGenerator"]
