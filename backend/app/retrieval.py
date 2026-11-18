"""Lexical retrieval over the course corpus.

BM25 over passages, with two additions that matter for course questions:

1. **Query expansion** for the vocabulary a student uses that the corpus does
   not ("deadline" -> "due", "marks" -> "weighting", "AI" -> "intelligent").
2. **Phrase matching** for *qualified names* — "assignment 1", "week 3",
   "question 4". Course documents are full of these, and treating them as
   independent words makes "assignment 1" match "assignment 2". A phrase hit is
   worth far more than the sum of its parts.

Every hit carries its score and the terms that matched, so the evidence panel
can show *why* a passage was selected.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .corpus import CORPUS, CourseDoc, Passage

K1 = 1.4
B = 0.72

STOPWORDS = frozenset(
    """
    a an the is are was were be been being to of in on at for with by from as it
    this that these those do does did can could should would will i my me you
    your we our if so but or and not what when where how am have has had there
    their they them he she about into than then also any up out get much many
    tell give show please thanks
    """.split()
)

#: Domain synonym table. Maps colloquial student phrasing onto corpus
#: vocabulary. Each pair is safe to expand because both terms refer to the
#: same course concept.
#:
#: A variant listed here is a *weak* association and carries
#: :data:`SYNONYM_WEIGHT`. A variant listed in :data:`STRONG_SYNONYMS` is
#: the same thing under another name — "books" and "readings" are one
#: concept in this course — and carries the full weight of the term the
#: student actually typed. That difference matters: with only weak
#: expansion, "Which books do I need to read?" matched the office-hours
#: notice ("Book through the module portal") more strongly than the
#: reading list, and the assistant answered that the module had no
#: reading list at all.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "deadline": ("due", "submission", "submit"),
    "due": ("deadline", "submission"),
    "mark": ("mark", "weighting", "percentage", "grade"),
    "marks": ("mark", "weighting", "percentage"),
    "weighting": ("weighting", "mark", "percentage"),
    "ai": ("ai", "intelligent", "artificial"),
    "artificial intelligence": ("ai", "intelligent"),
    "pass": ("referral", "fail", "resit"),
    "fail": ("referral", "resit", "zero"),
    "referral": ("referral", "resit"),
    "cheat": ("plagiarism", "integrity", "misconduct"),
    "plagiarism": ("plagiarism", "integrity"),
    "undeclared": ("undeclared", "declare", "declaration"),
    "declare": ("undeclared", "declare", "declaration"),
    "reference": ("referencing", "harvard", "source"),
    "referencing": ("referencing", "harvard"),
    "bibliography": ("referencing", "reference"),
    "week": ("week",),
    # "book" is genuinely ambiguous in this domain: a student asking about
    # the reading list means a textbook, while one booking a consultation
    # means a reservation. Mapping it to only the booking sense made
    # "Which books do I need to read?" retrieve the office-hours notice and
    # miss the reading list entirely, so the assistant claimed the module
    # had no reading list. Both senses are listed here and the retrieval
    # layer keeps the context-dependent disambiguation in
    # :func:`expand_query`.
    "book": ("booking", "book", "slot", "consultation", "reading", "read"),
    "books": ("book", "reading", "read"),
    "booking": ("booking", "book", "slot", "consultation"),    "slot": ("slot", "consultation", "booking"),
    "consult": ("consultation", "office hours", "slot"),
    "office hours": ("consultation", "office hours", "slot"),
    "cancel": ("cancel", "cancellation"),
    "cancellation": ("cancel", "cancellation"),
    "room": ("room", "seminar"),
    "seminar": ("seminar", "room"),
    "exam": ("exam", "paper"),
    "final exam": ("exam", "final"),
    "extension": ("extension", "deadline", "mitigating"),
    "feedback": ("feedback", "mark", "comments"),
    "cite": ("referencing", "cite", "source"),
    "sources": ("source", "referencing"),
    "late": ("late", "penalty", "penalised"),
    "penalty": ("late", "penalty", "penalised"),
    "revision": ("prepare", "preparation", "practice"),
    "prepare": ("prepare", "preparation"),
    "trust": ("trust", "reliab", "depend"),
    "credible": ("trust", "reliab"),
    "api": ("api", "key", "model"),
    "model": ("model",),
    "github": ("github", "repository", "repo"),
    "repository": ("repository", "github"),
    "diagram": ("diagram", "architecture"),
    "storyboard": ("storyboard", "interaction"),
    "read": ("reading", "readings", "read"),
    "reading": ("reading", "readings", "textbook"),
    "readings": ("reading", "readings", "textbook"),
    "textbook": ("reading", "textbook"),
    "article": ("reading", "paper"),
    "journal": ("reading", "journal"),
    "module": ("module",),
    "handbook": ("handbook", "module handbook"),
    "word": ("word", "words"),
    "words": ("word", "words"),
    "abstract": ("abstract",),
    "report": ("report",),
    "resit": ("resit", "referral"),
    "job": ("work", "commitment"),
}

#: Terms that are the *same course concept* as the term the student typed.
#:
#: These carry the full weight of the original term rather than the reduced
#: :data:`SYNONYM_WEIGHT`, because a student who asks for "books" is asking
#: for the reading list and a student who asks for "marks" is asking for
#: the weighting — the two are different words for one thing in the
#: corpus. Treating them as weak associations let an unrelated passage
#: that merely used the word outrank the passage that answers the question.
STRONG_SYNONYMS: dict[str, tuple[str, ...]] = {
    "book": ("reading", "readings", "textbook"),
    "books": ("reading", "readings", "textbook"),
    "read": ("reading", "readings"),
    "reading": ("reading", "readings"),
    "readings": ("reading", "readings"),
    "marks": ("mark", "weighting", "percentage"),
    "sources": ("source", "referencing"),
    "words": ("word",),
    "handbook": ("module handbook",),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def stem(token: str) -> str:
    """A deliberately small stemmer.

    Course documents are full of pairs like "extension" / "Extensions" and
    "assignment" / "assignments". Without folding the plural away, a student
    asking about an "extension" does not match the FAQ heading "Extensions",
    and the passage that answers their question is never retrieved.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


#: The synonym table keyed by *stemmed* term.
#:
#: The index and the query are both stemmed, so a table keyed by the raw
#: plural is dead code: "marks" stems to "mark" and never matches the
#: "marks" entry, and a variant such as "words" can never match an indexed
#: token either. Five of the sixty entries were silently unreachable that
#: way. Stemming both the keys and the variants makes the table agree with
#: the index it is used against.
_STEMMED_SYNONYMS: dict[str, tuple[str, ...]] = {
    stem(key): tuple(stem(variant) for variant in variants)
    for key, variants in SYNONYMS.items()
}

#: :data:`STRONG_SYNONYMS` keyed by stemmed term, with stemmed variants.
_STEMMED_STRONG_SYNONYMS: dict[str, tuple[str, ...]] = {
    stem(key): tuple(stem(variant) for variant in variants)
    for key, variants in STRONG_SYNONYMS.items()
}


def tokenize(text: str) -> list[str]:
    """Tokenise for indexing.

    Numbers are kept — they are highly discriminative in a course corpus
    ("assignment 1" versus "assignment 2").
    """
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if len(t) > 1 or t.isdigit() and t in "0123456789"]


def _kept(token: str) -> bool:
    if len(token) > 1:
        return token not in STOPWORDS
    return False


def tokenize_content(text: str) -> list[str]:
    """Tokenise with stopwords removed and plurals stemmed."""
    return [stem(t) for t in tokenize(text) if _kept(t)]


def expand_query(query: str) -> dict[str, float]:
    """Expand a query with synonym variants, as term -> weight.

    The *original* terms carry weight 1.0. Synonym variants carry a reduced
    weight, because an expansion is a weaker signal than what the student
    actually wrote. Without that distinction, asking about a "deadline"
    expands to "submit" and drags in passages about submission format, which
    then outrank the passage that states the deadline.

    Some words carry more than one course meaning, and expanding them into
    every sense at once drowns the right answer. "Book" means a textbook in
    a reading-list question and a reservation in a consultation question, so
    the reading sense is only activated when the query actually talks about
    reading, and the booking sense only when it talks about a session.
    """
    base = set(tokenize_content(query))
    weights = {term: 1.0 for term in base}

    lower = query.lower()
    for term in base:
        for variant, weight in _variants_for(term, lower):
            if weights.get(variant, 0.0) < weight:
                weights[variant] = weight

    for phrase, variants in SYNONYMS.items():
        if " " in phrase and phrase in lower:
            for variant in variants:
                weights.setdefault(stem(variant), SYNONYM_WEIGHT)

    # When "book" has been read as a textbook, the literal token "book" no
    # longer describes what the student wants. Left in, it keeps pulling in
    # the office-hours notice ("Book through the module portal"), which is
    # the reservation sense of the word — the very sense that was ruled
    # out. The equivalent terms already carry the full weight.
    if _book_means_reading(lower):
        weights.pop("book", None)

    return weights


#: Words that signal the question is about reading materials rather than
#: about making a booking. "book" is deliberately absent: it belongs to
#: both senses and cannot decide between them.
_READING_CUES = ("read", "reading", "readings", "textbook", "article", "journal")

#: Words that signal the question is about reserving a session. As with
#: "book", the word itself is not a cue.
_BOOKING_CUES = (
    "consult",
    "slot",
    "session",
    "appointment",
    "meeting",
    "reserv",
    "booking",
)


def _book_means_reading(lower_query: str) -> bool:
    """Whether "book" in this query means a textbook rather than a booking."""
    if "book" not in lower_query:
        return False
    wants_reading = any(cue in lower_query for cue in _READING_CUES)
    wants_booking = any(cue in lower_query for cue in _BOOKING_CUES)
    return wants_reading and not wants_booking


def _variants_for(term: str, lower_query: str) -> tuple[tuple[str, float], ...]:
    """Return the synonym variants valid for this term, with their weights.

    Each variant is paired with the weight it should carry: the full weight
    of the term the student typed for an equivalent term, and the reduced
    :data:`SYNONYM_WEIGHT` for a merely related one.
    """
    weak = _STEMMED_SYNONYMS.get(term, ())
    strong = _STEMMED_STRONG_SYNONYMS.get(term, ())

    if term != "book":
        return tuple((v, SYNONYM_WEIGHT) for v in weak) + tuple(
            (v, 1.0) for v in strong
        )

    wants_reading = any(cue in lower_query for cue in _READING_CUES)
    wants_booking = any(cue in lower_query for cue in _BOOKING_CUES)

    reading_sense = ("reading", "readings", "read", "textbook")
    booking_sense = ("booking", "book", "slot", "consultation")

    if wants_reading and not wants_booking:
        chosen = reading_sense
    elif wants_booking and not wants_reading:
        chosen = booking_sense
    elif wants_reading and wants_booking:
        # Both senses are present. Keep both, but neither at full strength:
        # the word "book" alone does not decide which document the student
        # means, so both readings stay available.
        chosen = reading_sense + booking_sense
    else:
        # Neither sense is signalled. "Which books do I need?" is about
        # reading materials far more often than about reservations, so the
        # reading sense is the safer default.
        chosen = reading_sense

    # A chosen variant that names the same concept as the term the student
    # typed keeps the full weight; the rest are weak associations.
    strong_choice = tuple(v for v in chosen if v in strong or v in reading_sense)
    weak_choice = tuple(v for v in chosen if v not in strong_choice)

    return tuple((v, 1.0) for v in strong_choice) + tuple(
        (v, SYNONYM_WEIGHT) for v in weak_choice
    )


#: Weight of a synonym-expanded term relative to a term the student wrote.
SYNONYM_WEIGHT = 0.35


_PHRASE_RE = re.compile(r"\b([a-z]{2,})\s*([0-9]+)\b")
_PHRASE3_RE = re.compile(r"\b([a-z]{2,})\s*([0-9]+)\s+([a-z]{3,})\b")


def extract_phrases(query: str) -> list[str]:
    """Extract *qualified names* from a query.

    A word or two immediately followed by a number, e.g. "assignment 1",
    "week 3", "question 4", "a2 brief". These are the phrases that must match
    verbatim.
    """
    lower = query.lower()
    phrases = [f"{m.group(1)} {m.group(2)}" for m in _PHRASE_RE.finditer(lower)]
    phrases += [
        f"{m.group(1)} {m.group(2)} {m.group(3)}" for m in _PHRASE3_RE.finditer(lower)
    ]
    return list(dict.fromkeys(phrases))


@dataclass(frozen=True)
class IndexedPassage:
    doc_id: str
    passage: Passage
    tf: dict[str, int]
    length: int


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    passage_id: str
    score: float
    matched_terms: tuple[str, ...]
    matched_phrases: tuple[str, ...]


def _build_index() -> tuple[dict[str, list[IndexedPassage]], list[IndexedPassage]]:
    postings: dict[str, list[IndexedPassage]] = {}
    all_entries: list[IndexedPassage] = []

    for doc in CORPUS:
        for passage in doc.passages:
            tokens = tokenize_content(f"{doc.title} {passage.heading} {passage.text}")
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            entry = IndexedPassage(
                doc_id=doc.id, passage=passage, tf=tf, length=len(tokens)
            )
            all_entries.append(entry)
            for term in tf:
                postings.setdefault(term, []).append(entry)

    return postings, all_entries


_POSTINGS, _ENTRIES = _build_index()
_TOTAL_PASSAGES = len(_ENTRIES)
_AVG_LEN = (sum(e.length for e in _ENTRIES) / _TOTAL_PASSAGES) if _TOTAL_PASSAGES else 1.0
_TITLE_BY_DOC = {d.id: d.title.lower() for d in CORPUS}

#: Multiplier applied to a passage from a document version that is still in
#: force. An old version of a document usually contains the *same* words as the
#: new one, so without this the superseded copy can out-rank the current one
#: on raw keyword overlap. The current version must win, and the old one is
#: still shown to the student as flagged evidence.
CURRENT_VERSION_BOOST = 1.6

#: Multiplier applied to a passage from a withdrawn or superseded version.
STALE_VERSION_MULTIPLIER = 0.75


def _version_multiplier(doc_id: str) -> float:
    doc = next((d for d in CORPUS if d.id == doc_id), None)
    if doc is None:
        return 1.0
    if doc.status == "current":
        return CURRENT_VERSION_BOOST
    if doc.status in ("superseded", "archived"):
        return STALE_VERSION_MULTIPLIER
    return 1.0

#: Weight of a phrase hit relative to the BM25 score.
PHRASE_WEIGHT = 8.0

#: Extra weight when the queried phrase is the passage's *section heading*.
#: A document whose section is literally "Week 3" is a better answer to
#: "what does Week 3 cover?" than one that merely mentions Week 3 in passing
#: inside a long paragraph.
HEADING_PHRASE_WEIGHT = 12.0


def _bm25(entry: IndexedPassage, terms: dict[str, float]) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    for term, weight in terms.items():
        postings = _POSTINGS.get(term)
        if not postings:
            continue
        tf = entry.tf.get(term, 0)
        if tf == 0:
            continue
        n = len(postings)
        idf = math.log(1 + (_TOTAL_PASSAGES - n + 0.5) / (n + 0.5))
        denom = tf + K1 * (1 - B + (B * entry.length) / _AVG_LEN)
        score += weight * idf * ((tf * (K1 + 1)) / denom)
        matched.append(term)
    return score, matched


def retrieve(query: str, limit: int = 12) -> list[SearchHit]:
    """Rank passages against a query. Each passage is scored exactly once."""
    terms = expand_query(query)
    phrases = extract_phrases(query)
    hits: list[SearchHit] = []

    for entry in _ENTRIES:
        score, matched = _bm25(entry, terms)
        matched_phrases: list[str] = []
        phrase_bonus = 0.0

        # Phrase matching checks the passage text and the document title. A
        # phrase in the title ("Assignment 1 Brief") identifies the whole
        # document, so it earns the full phrase boost.
        haystack = f"{entry.passage.text} {entry.passage.heading}".lower()
        heading = entry.passage.heading.lower()
        title = _TITLE_BY_DOC.get(entry.doc_id, "")
        for phrase in phrases:
            if phrase in haystack or phrase in title:
                matched_phrases.append(phrase)
                phrase_bonus += PHRASE_WEIGHT
                if phrase in heading:
                    phrase_bonus += HEADING_PHRASE_WEIGHT

        total = score + phrase_bonus
        if total <= 0:
            continue

        # A version that is still in force outranks an old copy of the same
        # document, and an old copy is damped but not hidden — the student
        # should still be able to see what changed.
        total *= _version_multiplier(entry.doc_id)

        hits.append(
            SearchHit(
                doc_id=entry.doc_id,
                passage_id=entry.passage.id,
                score=total,
                matched_terms=tuple(matched),
                matched_phrases=tuple(matched_phrases),
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def get_doc(doc_id: str) -> CourseDoc | None:
    for doc in CORPUS:
        if doc.id == doc_id:
            return doc
    return None


def get_passage(doc_id: str, passage_id: str) -> Passage | None:
    doc = get_doc(doc_id)
    if doc is None:
        return None
    for passage in doc.passages:
        if passage.id == passage_id:
            return passage
    return None
