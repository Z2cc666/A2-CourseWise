"""Evidence policy: freshness, sufficiency and conflict detection.

This module is the part that makes the system answerable rather than chatty.
It answers three questions the student cannot otherwise answer:

1. Is the document I am quoting still the one in force?  (freshness)
2. Do the retrieved passages actually support an answer?  (sufficiency)
3. Does a newer document disagree with the one I found?  (conflict)

A generic RAG system returns the top-k chunks regardless. Here each of those
questions can independently force the system to qualify, flag, or refuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .corpus import CORPUS, CourseDoc
from .retrieval import SearchHit, get_doc, tokenize_content

Freshness = str  # "current" | "expiring" | "expired" | "superseded" | "archived"
SupportLevel = str  # "supported" | "partial" | "insufficient"

#: Days before expiry at which a document is flagged as "expiring".
EXPIRING_WINDOW_DAYS = 30


def parse_date(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def format_date(iso: str) -> str:
    """Format an ISO date the way the course documents write them."""
    return parse_date(iso).strftime("%-d %B %Y")


def corpus_today() -> date:
    """The most recent publication date in the corpus, used as "today".

    Keeps the demo deterministic and reproducible regardless of when it runs.
    """
    return max(parse_date(d.updated_at) for d in CORPUS)


def days_between(start: date, end: date) -> int:
    return (end - start).days


def current_version_of(doc_key: str) -> CourseDoc | None:
    """The newest version of a document group."""
    group = [d for d in CORPUS if d.doc_key == doc_key]
    if not group:
        return None
    live = [d for d in group if d.status == "current"]
    pool = live or group
    return max(pool, key=lambda d: (parse_date(d.updated_at), len(d.passages)))


def versions_of(doc_key: str) -> list[CourseDoc]:
    """All versions of a document group, newest first."""
    return sorted(
        (d for d in CORPUS if d.doc_key == doc_key),
        key=lambda d: parse_date(d.updated_at),
        reverse=True,
    )


@dataclass(frozen=True)
class FreshnessVerdict:
    freshness: Freshness
    label: str
    detail: str
    superseded_by: tuple[str, str, str] | None = None  # (doc_id, title, updated_at)
    days_until_expiry: int | None = None


def assess_freshness(doc: CourseDoc, today: date) -> FreshnessVerdict:
    """Assess how current a single document version is, as of ``today``."""
    current = current_version_of(doc.doc_key)

    if current is not None and current.id != doc.id:
        return FreshnessVerdict(
            freshness="superseded",
            label="Superseded",
            detail=(
                f"This version was replaced on {format_date(current.updated_at)} by a "
                "newer version of the same document."
            ),
            superseded_by=(current.id, current.title, current.updated_at),
        )

    if doc.status == "archived":
        return FreshnessVerdict(
            freshness="archived",
            label="Withdrawn",
            detail=(
                "This document has been withdrawn and no longer represents the "
                "policy in force. Do not rely on it."
            ),
        )

    if doc.expires_at:
        days = days_between(today, parse_date(doc.expires_at))
        if days < 0:
            return FreshnessVerdict(
                freshness="expired",
                label="Expired",
                detail=(
                    f"The validity period of this document ended on "
                    f"{format_date(doc.expires_at)}. It may no longer reflect the "
                    "current rules."
                ),
                days_until_expiry=days,
            )
        if days <= EXPIRING_WINDOW_DAYS:
            return FreshnessVerdict(
                freshness="expiring",
                label="Expiring soon",
                detail=(
                    f"This document stops being valid on {format_date(doc.expires_at)}, "
                    f"in {days} days. Check whether a replacement has been published."
                ),
                days_until_expiry=days,
            )
        return FreshnessVerdict(
            freshness="current",
            label="Current",
            detail=f"Valid until {format_date(doc.expires_at)}.",
            days_until_expiry=days,
        )

    return FreshnessVerdict(
        freshness="current",
        label="Current",
        detail=f"Published {format_date(doc.updated_at)}. No expiry recorded.",
    )


# ---------------------------------------------------------------------- #
# Sufficiency                                                          #
# ---------------------------------------------------------------------- #


@dataclass(frozen=True)
class SufficiencyVerdict:
    level: SupportLevel
    confidence: float
    reasons: tuple[str, ...]
    next_steps: tuple[str, ...]


def _term_weight(term: str) -> float:
    """Inverse document frequency of a term across the corpus."""
    df = sum(
        1
        for d in CORPUS
        for p in d.passages
        if term in p.text.lower()
    )
    return math_log(1 + len(CORPUS) / max(1, df))


def math_log(value: float) -> float:
    import math

    return math.log(value)


def assess_sufficiency(query: str, hits: list[SearchHit]) -> SufficiencyVerdict:
    """Score how much of the query the retrieved passages actually cover.

    Coverage is measured over the *query's own* content terms. A term that
    appears in the question but in no retrieved passage is an uncovered part of
    the question, and it lowers confidence. Terms are weighted by how rare they
    are, so a missed distinctive term ("plagiarism") hurts more than a missed
    common one.
    """
    if not hits:
        return SufficiencyVerdict(
            level="insufficient",
            confidence=0.0,
            reasons=("No passage in the course documents matched this question.",),
            next_steps=(
                "Try naming the policy, assessment or week explicitly, e.g. "
                '"the exam format" or "Assignment 1 deadline".',
                "Ask the module team directly if the question is not covered by "
                "course documentation.",
            ),
        )

    query_terms = tokenize_content(query)
    if not query_terms:
        return SufficiencyVerdict(
            level="insufficient",
            confidence=0.0,
            reasons=("The question contains no searchable terms.",),
            next_steps=(
                'Ask a question about the course documents, for example "What is '
                'the exam format?"',
            ),
        )

    matched: set[str] = set()
    for hit in hits:
        matched.update(hit.matched_terms)
        for phrase in hit.matched_phrases:
            matched.update(tokenize_content(phrase))

    total_weight = 0.0
    covered_weight = 0.0
    uncovered: list[str] = []
    for term in query_terms:
        weight = _term_weight(term)
        total_weight += weight
        if term in matched:
            covered_weight += weight
        else:
            uncovered.append(term)

    coverage = covered_weight / total_weight if total_weight else 0.0

    top = hits[0].score
    strength = min(1.0, top / 8)
    consensus = min(1.0, len(hits) / 4) if len(hits) > 1 else 0.35
    phrase_boost = 0.1 if any(h.matched_phrases for h in hits) else 0.0

    confidence = round(
        min(1.0, 0.45 * strength + 0.3 * coverage + 0.15 * consensus + phrase_boost), 2
    )

    if coverage >= 0.6 and confidence >= 0.45:
        return SufficiencyVerdict(
            level="supported",
            confidence=confidence,
            reasons=(
                f"Retrieved {len(hits)} supporting passage"
                f"{'s' if len(hits) != 1 else ''} from the course documents.",
            ),
            next_steps=(),
        )

    if uncovered:
        shown = ", ".join(f'"{u}"' for u in uncovered[:4])
        verb = "is" if len(uncovered) == 1 else "are"
        reason = (
            "The passages retrieved do not cover every part of the question — "
            f"{shown} {verb} not mentioned in any of them."
        )
    else:
        reason = (
            "The retrieved passages only partially match the question, so the "
            "answer may not cover what you actually asked."
        )

    return SufficiencyVerdict(
        level="partial",
        confidence=confidence,
        reasons=(reason,),
        next_steps=(
            "Check the highlighted passages before relying on the answer, and "
            "rephrase using terms that appear in the course documentation.",
        ),
    )


# ---------------------------------------------------------------------- #
# Conflict detection                                                   #
# ---------------------------------------------------------------------- #


@dataclass(frozen=True)
class Conflict:
    doc_key: str
    title: str
    passage_id: str
    excerpt: str
    counter_doc_id: str
    counter_passage_id: str
    counter_excerpt: str
    kind: str  # "value-changed" | "rule-changed" | "policy-tightened"
    detail: str


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_DATE_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)
_PCT_RE = re.compile(r"\b(\d{1,3})\s?%")
_WORDS_RE = re.compile(r"\b(\d{3,4})\s+words\b", re.IGNORECASE)
_QUESTIONS_RE = re.compile(r"\b(\d{1,3})\s+questions\b", re.IGNORECASE)

#: Spelled-out counts that appear in the corpus ("three questions"). Without
#: these, a change from "three questions" to "four questions" is invisible to
#: the conflict detector, which is exactly the kind of change a student is
#: most likely to be caught out by.
_WORD_NUMBERS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}
_NUMBER_WORDS = "|".join(_WORD_NUMBERS)
_COUNT_UNIT_WORDS = "questions|words|minutes|hours|days|weeks|sources|marks"

_SPELLED_COUNT_RE = re.compile(
    rf"\b({_NUMBER_WORDS})[\s-]+({_COUNT_UNIT_WORDS})\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ComparableValue:
    kind: str  # "date" | "percentage" | "number" | "duration"
    unit: str  # "%" | "words" | "questions" | "minutes" | "date"
    value: str
    raw: str


def extract_comparable_values(text: str) -> list[ComparableValue]:
    """Pull out values that two versions could plausibly disagree about.

    Each value carries a *unit* so that two versions are only compared on the
    same kind of quantity. Without the unit, "Two questions are compulsory"
    (unchanged in both versions) could be paired against "four questions" and
    reported as a change that never happened.
    """
    out: list[ComparableValue] = []

    for m in _DATE_RE.finditer(text):
        raw = m.group(0)
        try:
            normalised = datetime.strptime(raw.title(), "%d %B %Y").date().isoformat()
        except ValueError:
            continue
        out.append(ComparableValue(kind="date", unit="date", value=normalised, raw=raw))

    for m in _PCT_RE.finditer(text):
        out.append(
            ComparableValue(kind="percentage", unit="%", value=m.group(1), raw=f"{m.group(1)}%")
        )

    for m in _WORDS_RE.finditer(text):
        out.append(
            ComparableValue(kind="number", unit="words", value=m.group(1), raw=f"{m.group(1)} words")
        )

    for m in _QUESTIONS_RE.finditer(text):
        out.append(
            ComparableValue(
                kind="number", unit="questions", value=m.group(1), raw=f"{m.group(1)} questions"
            )
        )

    for m in re.finditer(r"\b(\d{1,3})[\s-]?(minute|hour)s?\b", text, re.IGNORECASE):
        unit = m.group(2).lower() + "s"
        out.append(
            ComparableValue(kind="duration", unit=unit, value=m.group(1), raw=m.group(0))
        )

    for m in _SPELLED_COUNT_RE.finditer(text):
        number = _WORD_NUMBERS.get(m.group(1).lower())
        if number is None:
            continue
        unit = m.group(2).lower()
        kind = "duration" if unit in ("minutes", "hours", "days", "weeks") else "number"
        out.append(
            ComparableValue(kind=kind, unit=unit, value=str(number), raw=m.group(0))
        )

    return out


def _same_heading(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z]", "", s.lower())  # noqa: E731
    return norm(a) == norm(b)


def _classify(old: ComparableValue, new: ComparableValue) -> str:
    if old.kind in ("percentage", "number"):
        if int(old.value) < int(new.value):
            return "policy-tightened"
        return "rule-changed"
    return "value-changed"


def _primary_values(values: list[ComparableValue]) -> list[ComparableValue]:
    """Keep only the first value seen for each (kind, unit) pair.

    A passage may mention the same quantity more than once — "four questions,
    two compulsory and two optional" states the count of questions and then
    its breakdown. Comparing every mention would report the breakdown as a
    change. The *headline* value is the first one, so only that is compared.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ComparableValue] = []
    for value in values:
        key = (value.kind, value.unit)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def detect_conflicts() -> list[Conflict]:
    """Detect where two versions of a document disagree on a comparable value.

    A conflict is only reported when the newer passage mentions a value of the
    same *kind* but different content, under a matching section heading. This
    keeps false positives low: paraphrases that share no comparable value are
    not flagged as conflicts.
    """
    conflicts: list[Conflict] = []
    doc_keys = {d.doc_key for d in CORPUS}

    for doc_key in doc_keys:
        versions = versions_of(doc_key)
        if len(versions) < 2:
            continue
        newest, older = versions[0], versions[1]

        for old_passage in older.passages:
            if any(c.passage_id == old_passage.id for c in conflicts):
                continue
            old_values = _primary_values(extract_comparable_values(old_passage.text))

            for new_passage in newest.passages:
                if not _same_heading(old_passage.heading, new_passage.heading):
                    continue
                new_values = _primary_values(
                    extract_comparable_values(new_passage.text)
                )

                for old_value in old_values:
                    for new_value in new_values:
                        # Same kind *and* same unit: a change in the number of
                        # questions is not a change in the number of minutes.
                        if old_value.kind != new_value.kind:
                            continue
                        if old_value.unit != new_value.unit:
                            continue
                        if old_value.value == new_value.value:
                            continue
                        conflicts.append(
                            Conflict(
                                doc_key=doc_key,
                                title=newest.title,
                                passage_id=old_passage.id,
                                excerpt=old_passage.text,
                                counter_doc_id=newest.id,
                                counter_passage_id=new_passage.id,
                                counter_excerpt=new_passage.text,
                                kind=_classify(old_value, new_value),
                                detail=(
                                    f'The value "{old_value.raw}" in the earlier '
                                    f'version was replaced by "{new_value.raw}" in the '
                                    f"version published {format_date(newest.updated_at)}."
                                ),
                            )
                        )
                        break
                if any(c.passage_id == old_passage.id for c in conflicts):
                    break

    return conflicts


# ---------------------------------------------------------------------- #
# Composition                                                          #
# ---------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvidenceItem:
    doc_id: str
    doc_key: str
    title: str
    kind: str
    owner: str
    updated_at: str
    updated_at_label: str
    summary: str
    source_url: str | None
    passage_id: str
    heading: str
    text: str
    score: float
    matched_terms: tuple[str, ...]
    matched_phrases: tuple[str, ...]
    freshness: FreshnessVerdict


@dataclass(frozen=True)
class Warning:
    id: str
    severity: str  # "info" | "caution" | "warning"
    title: str
    detail: str
    evidence_ids: tuple[str, ...]


def build_evidence(hits: list[SearchHit], today: date) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for hit in hits:
        doc = get_doc(hit.doc_id)
        if doc is None:
            continue
        passage = next((p for p in doc.passages if p.id == hit.passage_id), None)
        if passage is None:
            continue
        items.append(
            EvidenceItem(
                doc_id=doc.id,
                doc_key=doc.doc_key,
                title=doc.title,
                kind=doc.kind,
                owner=doc.owner,
                updated_at=doc.updated_at,
                updated_at_label=format_date(doc.updated_at),
                summary=doc.summary,
                source_url=doc.source_url,
                passage_id=passage.id,
                heading=passage.heading,
                text=passage.text,
                score=round(hit.score, 3),
                matched_terms=hit.matched_terms,
                matched_phrases=hit.matched_phrases,
                freshness=assess_freshness(doc, today),
            )
        )
    return items
