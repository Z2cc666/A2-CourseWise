# CourseWise

A conversational assistant for course information. It answers from a versioned
corpus of course documents, shows the passage behind every claim, flags
guidance that has been superseded, and refuses when the evidence does not
support an answer.

**Report word count:** abstract 251 words, main report 1,086 words, total
1,337 words (diagrams, storyboard captions and references excluded).

---

## Run it

```bash
./run.sh              # creates .venv, installs deps, serves on :8000
./run.sh --dev        # with auto-reload
```

Open <http://127.0.0.1:8000>. No API key is needed — the extractive backend
answers every question on its own.

To use DeepSeek instead:

```bash
cp .env.example .env
# then set DEEPSEEK_API_KEY=sk-...
```

The key is never committed. Check which backend is live:

```bash
curl -s http://127.0.0.1:8000/api/health
```

The database is created and seeded on first run. Delete
`backend/data/coursewise.db` to start from an empty corpus.

## Check the work

```bash
.venv/bin/python -m unittest discover -s backend/tests -t backend   # 76 tests
.venv/bin/python tools/try_questions.py    # typical student questions
.venv/bin/python tools/check_deepseek.py   # DeepSeek handling, no key needed
```

The test suite is hermetic: it ignores any `.env` file and any key exported in
your shell, so it gives the same result on every machine.

To rebuild the Word report with the four diagrams and three storyboards:

```bash
.venv/bin/python tools/build_report_docx.py
```

This needs `mermaid-cli` (`mmdc`) and a Chrome or Chromium binary.

To regenerate the storyboards from the running interface:

```bash
node tools/capture_storyboard.js
node tools/assemble_storyboard.js
```

## What works

- SQLite storage for documents, passages, conversations, bookings and pending
  actions.
- BM25 retrieval with synonym expansion and qualified-name phrase matching
  ("Assignment 1" does not match the Assignment 2 brief). Ambiguous terms are
  disambiguated by context: "book" means a textbook in a reading-list question
  and a reservation in a booking question.
- A policy layer that assesses document freshness, detects conflicts between
  versions by comparing values *by unit*, and scores whether the retrieved
  passages cover the question.
- Extractive answer generation, with every claim attached to its source
  passage id.
- A DeepSeek backend constrained to the retrieved passages.
- A two-phase protocol for state changes — propose, preview, confirm — for
  booking a consultation slot. A request matching no slot reports
  `action-unavailable` rather than claiming a confirmation is pending.
- A plain HTML/CSS/JavaScript frontend: conversation list, message thread, and
  an evidence panel under each answer.

**Simulated:** the Anthropic Claude backend. The prompt and response handling
are complete and it is selected when `ANTHROPIC_API_KEY` is set, but it was
developed against the extractive engine and has not been run with a live key.

**Planned:** email confirmation for booked consultations, and multiple users.
Bookings are currently shared across everyone using one database.

## Technology stack

| Component | Choice |
| --- | --- |
| Backend | Python 3.13, FastAPI, Uvicorn |
| Database | SQLite (`backend/data/coursewise.db`) |
| Retrieval | Custom BM25, no vector DB |
| Frontend | Vanilla HTML / CSS / JS, no framework |
| Generation | Extractive sentence selection (default), DeepSeek, Anthropic |

## Where things are

| Path | Contents |
| --- | --- |
| `docs/report.md` | The report text, the source the Word report is built from |
| `CourseWise-A2-Project-Report.docx` | The submitted report: text, four diagrams, three storyboards |
| `docs/system-diagram.md` | Mermaid source for the four diagrams |
| `docs/figures/` | The rendered diagrams and storyboard sheets |
| `docs/storyboard.html` | Three storyboards, self-contained, open and print to PDF |
| `backend/app/corpus_seed.py` | The seed corpus; edit to change the course content |
| `backend/app/db.py` | The SQLite schema and every query in the system |
| `tools/build_report_docx.py` | Builds the Word report from the Markdown sources |
| `tools/capture_storyboard.js` | Captures the storyboard frames from the running interface |

## AI assistance

Claude (via Cursor) was used for code generation, documentation drafting and
test authoring. Every module has automated tests and the backend suite was run
after each change; the ranking, conflict-detection, stemming, warning-grouping
and answer-selection rules were all rewritten after the first implementation
failed its tests. The diagrams were rendered and checked against the running
implementation, and the storyboard frames were captured from the running
interface rather than drawn by hand.

No accompanying ZIP is submitted: all project material fits in the repository.
