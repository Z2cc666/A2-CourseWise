# CourseWise — Assignment 2 Project Report

**Total word count (abstract + main report): 1,337 words**
**Abstract word count: 251 words**
*(Main report: 1,086 words. Diagrams, storyboard captions, references and repository
links are excluded, as the brief specifies.)*

**Student:** z2cc
**Module:** CS-26352 Human-Centred Design for Intelligent Systems, University of Birmingham
**Repository:** `https://github.com/<your-username>/coursewise` — submitted commit: `<sha>`

## Abstract

CourseWise is a conversational assistant for course information. A student asks a
question in ordinary language; the assistant answers from a versioned corpus of
course documents and shows the passage behind every claim, the document's
publication date, and an explicit judgement of whether that document is still in
force. Three commitments shape the design. First, an answer is never generated
beyond the retrieved evidence: coverage of the question's own terms is measured,
and when coverage is insufficient the assistant refuses and says which part of
the question it could not support. Second, revised guidance is handled
explicitly. The corpus holds documents in several versions, and conflict
detection compares values by unit between versions, so a changed deadline,
weighting, word limit or exam duration is reported with the old value, the new
value and the date of the replacement, while the superseded passage stays
visible as flagged evidence. Third, the assistant cannot change anything on its
own: requests that alter state follow a two-phase protocol in which the system
previews the exact fields that would change, names the consequence, and writes
nothing until the student confirms with a single-use token. The interaction is a
conventional chat interface with saved conversations and an evidence panel
marking each passage as quoted, current or superseded. A SQLite database holds
the versioned corpus, the conversation history and the bookings. Retrieval,
policy assessment, extractive answer generation, a DeepSeek backend constrained
to the retrieved passages, and the confirmation protocol are implemented. Email
confirmation is specified but not built.

## 1. Introduction

Course information is scattered across documents that change without warning. A
student who misses the revision of a brief learns the wrong deadline, plans for
the wrong exam, and finds out after submitting. A conventional chatbot does not
help: it answers fluently from a document that may no longer apply and gives
no hint of its own age. The hard part is not retrieval but *currency* — making
it visible which guidance still applies. CourseWise answers from a versioned
corpus while showing its evidence, and refuses when the evidence does not reach
the question.

## 2. Background and design principles

Earlier work on this module examined how interface visibility affects a user's
mental model of an assistant and their sense of agency, and proposed a
graduated-visibility design: show a short plan before acting, surface only
consequential decisions during, and leave an editable history afterwards.

Four established ideas shape the implementation. Johnson-Laird's [1] account of
mental models and Norman's [2] gulf of evaluation point at the same requirement:
a user has to predict what the system will do and check what it did. Kulesza et
al. [3] found that explanation completeness, not soundness, improves a mental
model, and that oversimplified explanations reduce trust. Haggard [4] and Wu
et al. [5] separate transparency from control, transparency alone not improving
shared agency where direct control did. Parasuraman and Riley [6] and Luger and
Sellen [7] explain why a stale answer is misuse.

## 3. System design and implementation

### 3.1 Architecture

The system separates four concerns: retrieval finds candidate passages, a policy
layer decides which may be used, generation answers from whatever survives, and
the interface shows the reasoning. Keeping freshness, conflict and coverage
checks outside generation means the guarantees hold whichever backend is
selected, and the system is testable without a language model.

{{FIGURE 1}}

The running system is a FastAPI backend over SQLite, holding twelve versioned
documents across nine keys and forty-six passages, three with a superseded
predecessor. Retrieval is BM25, extended with a synonym table of sixty entries
and a phrase match for qualified names such as "Assignment 2". Two generation
backends sit behind the policy layer: a deterministic extractive engine, and a
DeepSeek endpoint instructed to answer only from the retrieved passages. The
frontend is a chat layout with an evidence panel marking each passage as
quoted, current or superseded. Seventy-six tests cover these behaviours.

### 3.2 Freshness and conflict detection

Retrieval ranks the version in force above its superseded predecessor: the two
share most of their wording, so overlap alone cannot separate them, and without
that weighting an old copy can quietly reinstate a withdrawn deadline — misuse
in the sense of Parasuraman and Riley [6]. Changed values are compared by unit
rather than as bare numbers, since two exam briefs both state how many
questions are compulsory and a bare comparison invents a change that never
happened, and one false alarm costs the student trust in every other answer
[3]. A changed value is reported as both the old and the new value plus the
replacement date, so the student holds neither belief — calibrated reliance,
for Jian et al. [8].

{{FIGURE 4}}

{{STORYBOARD 1}}

### 3.3 Answer path and refusal

{{FIGURE 2}}

The policy layer measures whether the retrieved passages actually cover the
question's terms. When coverage is insufficient the assistant refuses and names
the uncovered part rather than apologising, following Amershi et al. [9]
guideline 10 on scoping services when in doubt; an unsourced plausible answer
is worse than none, because the student cannot tell a guess from a citation.
Every claim is attached to a passage id and the passages are marked as quoted,
the only way to check an answer independently [2]. Refusals always carry a next
step, since one that dead-ends hands the problem straight back [7].

{{STORYBOARD 2}}

### 3.4 Controlled state change

{{FIGURE 3}}

The assistant cannot change anything on its own. Requests that alter state
follow a two-phase protocol: the system previews the exact fields that would
change, names the consequence, and writes nothing until the student confirms
with a single-use token. The assistant reads policy the student may not have
read, so an action on a stale premise is hard to undo [6]. Wu et al. [5] find
that control, not transparency, produces agency, which is why approval is
required rather than merely offered: the preview is visibility, but approving it
is the control that turns visibility into agency [4].

{{STORYBOARD 3}}

The language-model backend is optional and the extractive engine the default: it
is deterministic, so behaviour can be asserted in tests, and the constraints
live in the policy layer rather than the prompt [10]. A third backend has not
run live, so Figure 1 marks it simulated.

## 4. Development process and evaluation

The first retrieval implementation ranked a superseded brief above its
replacement, because the older text contained more occurrences of words like
"supersedes"; version weighting was introduced in response. A question about
an "extension" then failed to match a passage headed "Extensions", which led to
a light stemmer. Conflict detection compared bare numbers and produced a false
conflict about compulsory questions, leading to the unit-aware comparison. The
warning layer collapsed a current version with its predecessor.

Using the finished system on ordinary student questions exposed further faults.
A request for the reading list returned none, because "book" had been mapped
only to the reservation sense; disambiguating the senses fixed it. The same pass
found that five of the sixty synonym entries were unreachable, because the
index stems plurals while the table was keyed by the unstemmed word. Each was
found by use, not inspection. Seventy-six tests were written in response, and
the behaviours they assert — ranking the in-force version first, comparing
changed values by unit, refusing with a next step — are those the interface
promises.

## 5. Limitations

The corpus is a demonstration set written for this module, not the live module
page. Retrieval is lexical, so a question sharing no vocabulary with the
documents finds nothing, and refusal is correct there. There is no account
system: bookings and conversations are shared across one database. The
DeepSeek backend needs an API key, read from a git-ignored `.env` file; with no
key the extractive engine answers. Email confirmation for bookings is specified
but not built.

## 6. Conclusion

CourseWise treats the currency of a document as a first-class part of the
answer rather than a hidden detail of retrieval. The policy layer decides what
may be used, the interface shows the evidence and its age, and any state change
requires explicit confirmation. The limits are clear — one demonstration
corpus, lexical retrieval, no accounts — but the guarantees are testable.

## References

[1] Johnson-Laird, P.N. (1983) *Mental Models*. Cambridge, MA: Harvard University
Press.

[2] Norman, D.A. (2013) *The Design of Everyday Things*. Revised and expanded edn.
New York: Basic Books.

[3] Kulesza, T., Stumpf, S., Burnett, M., Yang, S., Kwan, I. and Wong, W.-K. (2013)
'Too much, too little, or just right? Ways explanations impact end users'
mental models', *Proceedings of the IEEE Symposium on Visual Language and
Human-Centric Computing*, pp. 3–10. doi: 10.1109/VLHCC.2013.6645235.

[4] Haggard, P. (2017) 'Sense of agency in the human brain', *Nature Reviews
Neuroscience*, 18(4), pp. 196–207. doi: 10.1038/nrn.2017.14.

[5] Wu, M., Liu, W., Wang, Y. and Yao, M.Z. (2025) 'Negotiating the shared agency
between humans & AI in the recommender system', *Extended Abstracts of the CHI
Conference on Human Factors in Computing Systems*, article 416, pp. 1–9.
doi: 10.1145/3706599.3719900.

[6] Parasuraman, R. and Riley, V. (1997) 'Humans and automation: Use, misuse,
disuse, abuse', *Human Factors*, 39(2), pp. 230–253.
doi: 10.1518/001872097778543886.

[7] Luger, L. and Sellen, A. (2016) '"Like having a really bad PA": The gulf between
user expectation and experience of conversational agents', *Proceedings of CHI
2016*, pp. 5286–5297. doi: 10.1145/2858036.2858288.

[8] Jian, J.-Y., Bisantz, A.M. and Drury, C.G. (2000) 'Foundations for an
Empirically Determined Scale of Trust in Automated Systems', *International
Journal of Cognitive Ergonomics*, 4(1), pp. 53–71.
doi: 10.1207/S15327566IJCE0401_04.

[9] Amershi, S., Weld, D., Vorvoreanu, M., Fourney, A., Nushi, B., Collisson, P.,
Suh, J., Iqbal, S., Bennett, P.N., Inkpen, K., Teevan, J., Kikin-Gil, R. and
Horvitz, E. (2019) 'Guidelines for Human-AI Interaction', *Proceedings of CHI
2019*, paper 269, pp. 1–13. doi: 10.1145/3290605.3300233.

[10] Liao, Q.V., Gruen, D. and Miller, S. (2020) 'Questioning the AI: Informing
Design Practices for Explainable AI User Experiences', *Proceedings of CHI
2020*, paper 260, pp. 1–15. doi: 10.1145/3313831.3376590.

*Reused material: the abstract was rewritten for this project. The documents in
the corpus were written for this module. The earlier literature review on
interface visibility, mental models and agency is reused and extended in
section 2.*
