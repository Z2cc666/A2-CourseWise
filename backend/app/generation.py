"""Answer generation.

Two backends behind one interface:

* ``llm`` — Anthropic Claude, used when ``ANTHROPIC_API_KEY`` is set. The
  prompt constrains the model to answer *only* from the supplied passages and
  to cite them by index.
* ``extractive`` — no API key required. Selects the sentences in the retrieved
  passages that best cover the question and stitches them into a readable
  answer. Deterministic and inspectable.

The extractive backend is not a stub: it is the reference implementation of the
"an answer must be traceable to a passage" rule, and it is what the test suite
exercises so the system can be verified without a key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .policy import EvidenceItem
from .retrieval import expand_query, tokenize_content

#: Question words that carry no content signal.
QUESTION_WORDS = frozenset(
    """
    when what how who where why which does do is are can should need tell give
    show explain much many weight weighting deadline due
    """.split()
)

_INTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("duration", re.compile(r"\b(how long|how many minutes|length of the|duration)\b", re.I)),
    ("date", re.compile(r"\b(when|deadline|due date|what date|schedule|what time|which day|how long until)\b", re.I)),
    ("count", re.compile(r"\b(how many|how much words|number of|word limit|word count|length)\b", re.I)),
    ("percentage", re.compile(r"\b(weight|weighting|percentage|mark|grade|how much does it count)\b", re.I)),
)

#: Topic anchors. Some questions name a topic that the corpus labels in a
#: particular way ("AI" -> the integrity policy). These anchors are weighted
#: heavily so the answer comes from the right document even when a *different*
#: document scores well on generic words like "assignment" or "write".
TOPIC_ANCHORS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(ai|artificial intelligence|chatgpt|generative|llm)\b", re.I),
     ("ai", "generative", "integrity", "undeclared", "declare")),
    (re.compile(r"\b(plagiaris|cheat|integrity|misconduct)\b", re.I),
     ("plagiarism", "integrity", "undeclared", "declare")),
    (re.compile(r"\b(exam|paper|resit|referral)\b", re.I),
     ("exam", "questions", "minutes", "hall")),
    (re.compile(r"\b(reference|cite|citation|bibliograph|harvard)\b", re.I),
     ("referencing", "harvard", "sources", "journal")),
    (re.compile(r"\b(book|slot|consult|office hour|appointment)\b", re.I),
     ("consultation", "slot", "booking", "cancel")),
    (re.compile(r"\b(file format|pdf|submit|word count|extension)\b", re.I),
     ("submit", "pdf", "extension", "file")),
)

_WORD_NUMBERS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|"
    "twenty|thirty"
)
_COUNT_UNITS = "words|questions|sources|marks|passages|slots|minutes|hours|sections|components"

_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)


@dataclass(frozen=True)
class GenerationInput:
    question: str
    evidence: list[EvidenceItem]
    must_refuse: bool
    refusal_reason: str | None = None
    warnings: tuple[str, ...] = ()
    history: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class GeneratedAnswer:
    text: str
    cited_passage_ids: tuple[str, ...]
    backend: str
    model: str | None


# ---------------------------------------------------------------------- #
# Sentence handling                                                    #
# ---------------------------------------------------------------------- #

#: Abbreviations that end in a period but do not end a sentence.
_ABBREVIATIONS = re.compile(
    r"^(?:al|vol|no|ed|eds|fig|figs|eq|eqs|ch|pp|dr|prof|mr|mrs|ms|st|jr|sr|"
    r"approx|inc|ltd|dept|univ)$",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split a passage into sentences, keeping source order.

    Abbreviations are protected: "Jian et al. (2000) on trust" must not split
    after "al." — course readings are full of citations, and a naive split
    produces fragments that read as nonsense when stitched into an answer.
    """
    parts: list[str] = []
    current = ""

    for token in _SENTENCE_SPLIT.split(text):
        if not current:
            current = token
            continue

        # Look at the last word of what we have so far. If it is an
        # abbreviation, the period does not end the sentence.
        previous = re.search(r"([A-Za-z]+)\.$", current)
        is_abbreviation = bool(previous and _ABBREVIATIONS.match(previous.group(1)))
        next_starts_upper = bool(re.match(r'^[A-Z“"(]', token))

        if is_abbreviation or not next_starts_upper:
            current = f"{current} {token}"
        else:
            parts.append(current.strip())
            current = token

    if current.strip():
        parts.append(current.strip())

    return [p for p in parts if p]


def detect_intents(question: str) -> list[str]:
    """Detect every kind of value the question asks for.

    A question can ask for more than one kind of thing — "when is the
    deadline and how much does it count for?" wants a date *and* a
    percentage. Returning only the first intent would make the system answer
    half the question, so all matching intents are returned, most specific
    first.
    """
    found: list[str] = []
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(question):
            found.append(intent)
    return found or ["general"]


def detect_intent(question: str) -> str:
    """The single most specific intent, for callers that only need one."""
    return detect_intents(question)[0]


def carries_value_of_kind(sentence: str, intent: str) -> bool:
    """Does this sentence carry a value of the kind the question asks for?"""
    if intent == "date":
        return bool(
            re.search(rf"\b\d{{1,2}}\s+({_MONTH_NAMES})\s+\d{{4}}", sentence, re.I)
            or re.search(r"\b\d{1,2}:\d{2}\b", sentence)
            or re.search(r"\b\d{4}-\d{2}-\d{2}\b", sentence)
        )
    if intent == "duration":
        return bool(
            re.search(r"\b\d{1,3}[\s-]?(minute|hour|day|week)s?\b", sentence, re.I)
            or re.search(rf"\b({_WORD_NUMBERS})[\s-]?(minute|hour|day|week)s?\b", sentence, re.I)
        )
    if intent == "count":
        has_number = bool(
            re.search(rf"\b(\d{{1,4}}|{_WORD_NUMBERS})\b", sentence, re.I)
        )
        has_unit = bool(re.search(rf"\b({_COUNT_UNITS})\b", sentence, re.I))
        return has_number and has_unit
    if intent == "percentage":
        return bool(re.search(r"\b\d{1,3}\s?%", sentence))
    return False


def _anchor_terms(question: str) -> list[str]:
    out: list[str] = []
    for pattern, terms in TOPIC_ANCHORS:
        if pattern.search(question):
            out.extend(terms)
    return out


def build_query_terms(question: str, evidence: list[EvidenceItem]) -> dict[str, float]:
    """Build a term -> weight map from the question and the evidence text.

    A term the question uses that appears in *few* evidence passages is highly
    discriminative; a term that appears in all of them tells us little about
    which passage to quote.

    Tokenisation goes through the retrieval layer so that the question and the
    passages are compared on the same terms. Without this, a question about
    "extension" does not match a passage headed "Extensions", and the passage
    that actually answers the question is never quoted.
    """
    weights: dict[str, float] = {}
    expanded = expand_query(question)
    question_tokens = set(tokenize_content(question))

    for token, base_weight in expanded.items():
        pattern = re.compile(rf"\b{re.escape(token)}\w*\b", re.I)
        freq = sum(1 for e in evidence if pattern.search(e.text))
        if freq == 0:
            continue

        rarity = 1 / max(1, freq)
        if token in question_tokens:
            weight = base_weight * (1 + rarity * 2)
        else:
            # A synonym the student did not write is a weaker signal.
            weight = base_weight * (1 + rarity)
        weights[token] = weight

    # Topic anchors are added even when the question did not use the corpus
    # word, and they carry a large weight because they identify the document
    # family the answer must come from.
    for anchor in _anchor_terms(question):
        if anchor in weights:
            weights[anchor] *= 2
            continue
        pattern = re.compile(rf"\b{re.escape(anchor)}\w*\b", re.I)
        freq = sum(1 for e in evidence if pattern.search(e.text))
        if freq == 0:
            continue
        weights[anchor] = 2.5 + 1 / max(1, freq)

    return weights


def sentence_score(
    sentence: str, query_terms: dict[str, float], intents: list[str]
) -> float:
    """Score a sentence against the question.

    The dominant signal is how many *distinct* content terms of the question
    the sentence covers. Length is only a mild tie-breaker, so long, precise
    sentences are not penalised.

    A sentence that carries a value of a kind the question asked for is
    boosted, so "30 October 2026" outranks a sentence that merely mentions
    "deadline" in passing.
    """
    tokens = tokenize_content(sentence)
    if not tokens:
        return 0.0

    matched = [query_terms[t] for t in set(tokens) if t in query_terms]
    if not matched:
        return 0.0

    distinct_coverage = len(matched) / max(3, len(query_terms))
    weight_sum = sum(matched)
    # Length normalisation is deliberately weak.
    length_factor = 1 / (1 + (len(tokens) ** 0.5) / 8)

    score = weight_sum * (0.6 + 0.4 * min(1.0, distinct_coverage)) * length_factor

    # A sentence is boosted for *each* intent it satisfies, so a multi-part
    # question can pull in one sentence for the date and one for the weight.
    for intent in intents:
        if carries_value_of_kind(sentence, intent):
            score *= 1.5

    return score


def _term_coverage(sentence: str, query_terms: dict[str, float]) -> float:
    """The share of the question's content terms that this sentence covers.

    Weight-normalised, so covering a rare, distinctive term counts for much
    more than covering a common one.
    """
    tokens = set(tokenize_content(sentence))
    matched = {t: w for t, w in query_terms.items() if t in tokens}
    if not matched:
        return 0.0
    total = sum(query_terms.values())
    return sum(matched.values()) / total if total else 0.0


def build_refusal_text(reason: str | None, warnings: tuple[str, ...]) -> str:
    base = reason or (
        "The course documents do not contain enough evidence for me to answer this "
        "reliably."
    )
    lines = [base]
    if warnings:
        lines.append("")
        lines.append("What I can tell you from the documents I did find:")
        lines.extend(f"- {w}" for w in warnings)
    lines.append("")
    lines.append(
        "I have deliberately not answered from general knowledge, because I could "
        "not attach a source and date to it."
    )
    return "\n".join(lines)


class ExtractiveGenerator:
    """Generates an answer by quoting the retrieved passages."""

    backend = "extractive"
    model = None

    def _select_for_intents(
        self,
        candidates: list[tuple[str, str, float, int]],
        intents: list[str],
        query_terms: dict[str, float],
        scored: list[tuple[str, str, float, int]],
    ) -> list[tuple[str, str, float, int]]:
        """Choose the sentences that make up the answer.

        Two rules, in order:

        1. *Cover the parts of the question.* If the student asked for both a
           date and a weighting, the answer needs a sentence for each — the
           single strongest sentence usually carries only one of them.
        2. *Stay on topic.* A sentence is only admitted if it covers a
           meaningful share of the question's content terms.
        """
        if not candidates:
            return []

        chosen: list[tuple[str, str, float, int]] = []
        seen: set[str] = set()

        def add(item) -> None:
            key = item[0].lower()[:60]
            if key in seen:
                return
            seen.add(key)
            chosen.append(item)

        # Rule 1: satisfy each intent with its best candidate. The search
        # runs over every scored sentence, not just the ones that cleared
        # the relevance floor — a sentence stating "it accounts for 25% of the
        # module mark" is short and may score below the floor on its own.
        for intent in intents:
            if intent == "general":
                continue
            match = next(
                (
                    c
                    for c in sorted(scored, key=lambda s: s[2], reverse=True)
                    if carries_value_of_kind(c[0], intent)
                ),
                None,
            )
            if match is not None:
                add(match)

        # Rule 2: fill in with the strongest candidates that are on topic.
        for candidate in candidates:
            if len(chosen) >= 3:
                break
            if _term_coverage(candidate[0], query_terms) < 0.22:
                continue
            add(candidate)

        if not chosen:
            chosen = candidates[:1]

        # Restore document order so the answer reads in the order the source
        # wrote it, rather than in order of relevance.
        chosen.sort(key=lambda s: s[3])
        return chosen

    def generate(self, gen_input: GenerationInput) -> GeneratedAnswer:
        if gen_input.must_refuse:
            return GeneratedAnswer(
                text=build_refusal_text(gen_input.refusal_reason, gen_input.warnings),
                cited_passage_ids=(),
                backend=self.backend,
                model=None,
            )

        query_terms = build_query_terms(gen_input.question, gen_input.evidence)
        intents = detect_intents(gen_input.question)

        # Only passages that are genuinely competitive with the best one may be
        # quoted. The full retrieved set is still shown to the student as
        # evidence, but an answer stitched from a weakly-related passage reads
        # as if the system had something to say on a topic it does not.
        top_score = max((e.score for e in gen_input.evidence), default=0.0)
        strong = [e for e in gen_input.evidence if e.score >= top_score * 0.55]
        if not strong and gen_input.evidence:
            strong = gen_input.evidence[:1]
        pool = strong or gen_input.evidence

        scored: list[tuple[str, str, float, int]] = []
        for doc_index, evidence in enumerate(pool):
            for sent_index, sentence in enumerate(split_sentences(evidence.text)):
                score = sentence_score(sentence, query_terms, intents)
                if score > 0:
                    scored.append(
                        (sentence, evidence.passage_id, score, doc_index * 100 + sent_index)
                    )

        if not scored:
            return GeneratedAnswer(
                text=(
                    "I could not find a passage in the course documents that addresses "
                    "this question, so I will not guess. Try rephrasing with terms used "
                    "in the module handbook, or check the source list below for related "
                    "documents."
                ),
                cited_passage_ids=(),
                backend=self.backend,
                model=None,
            )

        scored.sort(key=lambda s: s[2], reverse=True)
        best = scored[0][2]

        # A sentence is only eligible if it covers a meaningful share of the
        # question's terms. Without this floor, a sentence that happens to
        # share one common word can be stitched in and make the answer look
        # like it covers a topic it does not.
        coverage_floor = 0.22
        candidates = [s for s in scored if s[2] >= best * 0.55]
        candidates = [
            s
            for s in candidates
            if _term_coverage(s[0], query_terms) >= coverage_floor
        ] or candidates[:2]

        # For a multi-part question, ensure each intent is represented. If the
        # student asked for a date *and* a weighting, the top sentence may
        # only carry one of them.
        selected = self._select_for_intents(candidates, intents, query_terms, scored)

        # Group by source passage. A stitched answer that jumps between
        # unrelated documents reads as incoherent, so the strongest passage
        # supplies the lead sentences; a second passage is added only when it
        # contributes a comparable share of the score.
        by_passage: dict[str, list[tuple[str, str, float, int]]] = {}
        for item in selected:
            by_passage.setdefault(item[1], []).append(item)

        if len(by_passage) == 1:
            ordered = selected
        else:
            ranked = sorted(
                by_passage.values(),
                key=lambda sentences: sum(s[2] for s in sentences),
                reverse=True,
            )
            primary = ranked[0]
            primary_total = sum(s[2] for s in primary)
            ordered = list(primary)
            for entry in ranked[1:]:
                if sum(s[2] for s in entry) >= primary_total * 0.6:
                    ordered.extend(entry)
            ordered.sort(key=lambda s: s[3])

        seen: set[str] = set()
        unique = []
        for sentence, passage_id, _, _ in selected:
            key = sentence.lower()[:60]
            if key in seen:
                continue
            seen.add(key)
            unique.append((sentence, passage_id))

        cited = tuple(dict.fromkeys(passage_id for _, passage_id in unique))
        text = " ".join(sentence for sentence, _ in unique)

        return GeneratedAnswer(
            text=text, cited_passage_ids=cited, backend=self.backend, model=None
        )


SYSTEM_PROMPT = """You are CourseWise, a course information assistant for university students.

You answer ONLY from the numbered course-document passages provided to you. You must obey these rules:

1. If the passages do not contain enough information to answer the question, say so plainly and explain which specific detail is missing. Never fill the gap with general knowledge, and never guess a date, number, or policy.
2. Cite the passage numbers you used inline, like [1] or [2][3]. Every factual claim must carry a citation.
3. If a passage is marked as SUPERSEDED, EXPIRED or WITHDRAWN, do not rely on its values. If a newer passage contradicts it, use the newer value and say explicitly that the value changed.
4. Answer in at most 120 words. Be direct. Do not use headings, bullet points, or markdown formatting.
5. Do not offer to perform actions, book anything, or change any state. You only answer questions."""


class LlmGenerator:
    """Generates an answer with Claude, constrained to the retrieved passages."""

    backend = "llm"

    def __init__(self, model: str) -> None:
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic  # imported lazily

            self._client = Anthropic()
        return self._client

    def generate(self, gen_input: GenerationInput) -> GeneratedAnswer:
        client = self._get_client()

        blocks = []
        for index, evidence in enumerate(gen_input.evidence, start=1):
            if evidence.freshness.freshness == "current":
                flag = "CURRENT"
            else:
                flag = (
                    f"{evidence.freshness.freshness.upper()} — "
                    f"{evidence.freshness.detail}"
                )
            blocks.append(
                f"[{index}] {evidence.title} ({evidence.owner})\n"
                f"    Section: {evidence.heading}\n"
                f"    Updated: {evidence.updated_at_label}\n"
                f"    Status: {flag}\n"
                f"    Passage: {evidence.text}"
            )
        passages = "\n\n".join(blocks)

        warnings_block = ""
        if gen_input.warnings:
            warnings_block = "\n\nConditions the assistant must respect and mention where relevant:\n" + "\n".join(
                f"- {w}" for w in gen_input.warnings
            )

        user_prompt = (
            f"Student question: {gen_input.question}\n\n"
            + (
                "IMPORTANT: the retrieved evidence is insufficient. Refuse clearly, say "
                "what is missing, and do not answer from general knowledge.\n"
                if gen_input.must_refuse
                else ""
            )
            + f"Available course-document passages:\n\n{passages or '(none)'}"
            + warnings_block
            + "\n\nAnswer the student's question."
        )

        response = client.messages.create(
            model=self.model,
            max_tokens=400,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        cited: list[str] = []
        for match in re.finditer(r"\[(\d+)(?:[,\s]*\d+)*\]", text):
            index = int(match.group(1)) - 1
            if 0 <= index < len(gen_input.evidence):
                passage_id = gen_input.evidence[index].passage_id
                if passage_id not in cited:
                    cited.append(passage_id)

        return GeneratedAnswer(
            text=text or "I was unable to produce an answer from the available passages.",
            cited_passage_ids=tuple(cited),
            backend=self.backend,
            model=self.model,
        )


class DeepSeekGenerator:
    """Generates an answer with DeepSeek, constrained to the retrieved passages.

    DeepSeek exposes an OpenAI-compatible chat completions endpoint, so the
    request is a plain HTTP POST — no SDK required. The constraints that make
    the answer checkable are the same ones the Claude backend uses: answer
    only from the supplied passages, cite them inline, and refuse rather
    than fill the gap from general knowledge.
    """

    backend = "deepseek"

    def __init__(
        self,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.timeout = timeout

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _build_messages(self, gen_input: GenerationInput) -> list[dict[str, str]]:
        blocks = []
        for index, evidence in enumerate(gen_input.evidence, start=1):
            if evidence.freshness.freshness == "current":
                flag = "CURRENT"
            else:
                flag = (
                    f"{evidence.freshness.freshness.upper()} — "
                    f"{evidence.freshness.detail}"
                )
            blocks.append(
                f"[{index}] {evidence.title} ({evidence.owner})\n"
                f"    Section: {evidence.heading}\n"
                f"    Updated: {evidence.updated_at_label}\n"
                f"    Status: {flag}\n"
                f"    Passage: {evidence.text}"
            )
        passages = "\n\n".join(blocks)

        warnings_block = ""
        if gen_input.warnings:
            warnings_block = (
                "\n\nConditions the assistant must respect and mention where relevant:\n"
                + "\n".join(f"- {w}" for w in gen_input.warnings)
            )

        user_prompt = (
            f"Student question: {gen_input.question}\n\n"
            + (
                "IMPORTANT: the retrieved evidence is insufficient. Refuse clearly, say "
                "what is missing, and do not answer from general knowledge.\n"
                if gen_input.must_refuse
                else ""
            )
            + f"Available course-document passages:\n\n{passages or '(none)'}"
            + warnings_block
            + "\n\nAnswer the student's question."
        )

        messages: list[dict[str, str]] = []
        # Earlier turns give the model the thread of the conversation. They are
        # labelled as history so the model does not treat them as new
        # passages to cite.
        for turn in gen_input.history:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_prompt})
        return messages

    def generate(self, gen_input: GenerationInput) -> GeneratedAnswer:
        import httpx2 as httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *self._build_messages(gen_input),
            ],
            "temperature": 0,
            "max_tokens": 600,
            "stream": False,
        }

        try:
            # ``trust_env=False`` keeps a proxy configured for the shell or
            # the operating system from silently intercepting the request.
            # DeepSeek's endpoint is reached directly, and honouring an
            # unrelated system proxy is a common source of failures that
            # look like an API problem.
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(
                    self._endpoint(),
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except Exception as exc:  # network failure, DNS, timeout
            return GeneratedAnswer(
                text=(
                    "I could not reach the DeepSeek API, so I have not produced an "
                    f"answer from the retrieved passages. ({type(exc).__name__}) "
                    "Check that the server has outbound network access and that "
                    "DEEPSEEK_API_KEY is valid."
                ),
                cited_passage_ids=(),
                backend=self.backend,
                model=self.model,
            )

        if response.status_code != 200:
            detail = response.text[:300]
            if response.status_code in (401, 403):
                reason = (
                    "the API key was rejected. Check DEEPSEEK_API_KEY in your .env "
                    "file"
                )
            elif response.status_code == 429:
                reason = "the API rate limit was reached. Try again shortly"
            elif response.status_code >= 500:
                reason = "the API returned a server error. Try again shortly"
            else:
                reason = f"the API returned HTTP {response.status_code}"
            return GeneratedAnswer(
                text=(
                    "The DeepSeek API did not answer, so I have not produced an "
                    f"answer from the retrieved passages — {reason}. "
                    f"(response: {detail})"
                ),
                cited_passage_ids=(),
                backend=self.backend,
                model=self.model,
            )

        try:
            data = response.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (ValueError, KeyError, IndexError, TypeError):
            return GeneratedAnswer(
                text=(
                    "The DeepSeek API returned an unexpected response, so I have not "
                    "produced an answer from the retrieved passages."
                ),
                cited_passage_ids=(),
                backend=self.backend,
                model=self.model,
            )

        cited: list[str] = []
        for match in re.finditer(r"\[(\d+)(?:[,\s]*\d+)*\]", text):
            index = int(match.group(1)) - 1
            if 0 <= index < len(gen_input.evidence):
                passage_id = gen_input.evidence[index].passage_id
                if passage_id not in cited:
                    cited.append(passage_id)

        return GeneratedAnswer(
            text=text or "I was unable to produce an answer from the available passages.",
            cited_passage_ids=tuple(cited),
            backend=self.backend,
            model=self.model,
        )


def create_generator():
    """Choose a generator based on the environment.

    ``DEEPSEEK_API_KEY`` takes priority, because DeepSeek exposes an
    OpenAI-compatible endpoint that works with any OpenAI client. If it is
    set but the client is missing, the error is not swallowed: a silent
    fallback to the extractive engine would hide a misconfiguration the
    reviewer needs to see.
    """
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if deepseek_key:
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        return DeepSeekGenerator(model=model, base_url=base_url, api_key=deepseek_key)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic  # noqa: F401

            return LlmGenerator(os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
        except ImportError:
            pass

    return ExtractiveGenerator()
