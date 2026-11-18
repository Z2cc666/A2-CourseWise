"""HTTP API for the CourseWise assistant.

Endpoints
    GET  /api/health              — service and backend status
    POST /api/ask                 — ask a question, get an evidence-backed answer
    POST /api/actions/{id}/confirm — commit a proposed state change
    POST /api/actions/{id}/cancel  — discard a proposed state change
    GET  /api/bookings            — list confirmed bookings
    GET  /api/slots               — published consultation slots
    GET  /api/documents           — the corpus, for the evidence browser
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .actions import ActionStore, format_slot_date
from .corpus import CORPUS, MODULE
from .db import DatabaseLocked, db as database
from .envfile import load_env

# Load .env before anything reads the environment, so the app picks up the
# DeepSeek key no matter how it was started (run.sh, uvicorn, a debugger).
load_env()

from .orchestrator import Orchestrator  # noqa: E402
from .policy import assess_freshness, corpus_today, format_date  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent.parent / "frontend"

app = FastAPI(
    title="CourseWise API",
    description="Evidence-grounded course information assistant.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

store = ActionStore()
orchestrator = Orchestrator(store=store)


@app.middleware("http")
async def disable_static_caching(request, call_next):
    """Make the browser revalidate the frontend on every load.

    Starlette's ``StaticFiles`` sends an ETag and a Last-Modified date but no
    Cache-Control, so browsers apply *heuristic* caching: they may serve a
    stale copy without asking the server. During development that means an
    edited ``app.js`` is paired with a new ``index.html``, and the two
    disagree about which element ids exist. The application then fails
    silently, half way through initialisation.

    ``no-cache`` does not forbid caching, it requires revalidation — which
    is exactly right for a locally served application whose files change.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.exception_handler(DatabaseLocked)
async def handle_database_locked(request, exc: DatabaseLocked):
    """Report a locked database as a conflict, not a server fault.

    Another program holding the file — a database browser, most often — is a
    condition the user can resolve by closing it. A 500 with a stack trace
    in the terminal tells them nothing; a 409 with an explanation tells them
    what to do.
    """
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "error": "database-locked"},
    )


# ---------------------------------------------------------------------- #
# Request models                                                       #
# ---------------------------------------------------------------------- #


class AskRequest(BaseModel):
    question: str = Field(..., description="The student's question.")
    allow_action: bool = Field(
        default=True, description="Allow the assistant to propose state changes."
    )
    conversation_id: str | None = Field(
        default=None, description="Continue an existing conversation."
    )


class ConversationRequest(BaseModel):
    title: str | None = Field(default=None, description="Optional title.")


# ---------------------------------------------------------------------- #
# API routes                                                           #
# ---------------------------------------------------------------------- #


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "backend": orchestrator.generator.backend,
        "model": orchestrator.generator.model,
        "today": format_date(corpus_today().isoformat()),
        "documents": len(CORPUS),
        "module": MODULE,
    }


@app.post("/api/ask")
async def ask(request: AskRequest) -> dict:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="A non-empty 'question' is required.")

    conversation_id = request.conversation_id
    if conversation_id and database.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="That conversation does not exist.")

    # Earlier turns give the model the thread of the conversation. The
    # current question is excluded because it is sent separately.
    history = database.recent_turns(conversation_id, limit=8) if conversation_id else []

    # A locked database is handled by the application-wide handler below,
    # which turns it into a 409 with an explanation.
    response = await orchestrator.handle(
        request.question,
        allow_action=request.allow_action,
        history=history,
    )
    payload = response.to_dict()

    if conversation_id:
        database.add_message(conversation_id, "user", request.question.strip())
        database.add_message(
            conversation_id,
            "assistant",
            payload["answer"],
            citations=[s["id"] for s in payload["sources"] if s.get("cited")],
        )

    return payload


# ---------------------------------------------------------------------- #
# Conversations                                                         #
# ---------------------------------------------------------------------- #


@app.get("/api/conversations")
def list_conversations() -> dict:
    return {"conversations": database.list_conversations()}


@app.post("/api/conversations")
def create_conversation(request: ConversationRequest) -> dict:
    title = (request.title or "").strip() or "New conversation"
    conversation_id = database.create_conversation(title)
    return {"conversation": database.get_conversation(conversation_id)}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    conversation = database.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="That conversation does not exist.")
    return {
        "conversation": conversation,
        "messages": database.list_messages(conversation_id),
    }


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    if not database.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="That conversation does not exist.")
    return {"ok": True}


@app.post("/api/actions/{action_id}/confirm")
def confirm_action(action_id: str) -> dict:
    action, booking, error = store.commit(action_id)
    if error is not None:
        raise HTTPException(status_code=409, detail=error)

    message = (
        f"Consultation booked for {format_slot_date(booking.slot_date)} at "
        f"{booking.slot_time}. A confirmation email will be sent."
        if action.kind == "book_consultation"
        else (
            f"Booking cancelled. The slot on {format_slot_date(booking.slot_date)} at "
            f"{booking.slot_time} has been released."
        )
    )
    return {
        "ok": True,
        "action": action.to_dict(),
        "booking": booking.to_dict(),
        "message": message,
    }


@app.post("/api/actions/{action_id}/cancel")
def cancel_action(action_id: str) -> dict:
    error = store.cancel(action_id)
    if error is not None:
        raise HTTPException(status_code=409, detail=error)
    return {
        "ok": True,
        "message": "Nothing was changed. The proposed action has been discarded.",
    }


@app.get("/api/bookings")
def list_bookings() -> dict:
    return {"bookings": [b.to_dict() for b in store.list_bookings()]}


@app.get("/api/slots")
def list_slots() -> dict:
    return {
        "slots": [
            {
                **slot,
                "label": format_slot_date(slot["date"]),
                "free": store.slot_available(slot["date"], slot["time"]),
            }
            for slot in database.list_slots()
        ]
    }


@app.get("/api/documents")
def list_documents() -> dict:
    today = corpus_today()
    return {
        "today": format_date(today.isoformat()),
        "documents": [
            {
                "id": doc.id,
                "docKey": doc.doc_key,
                "title": doc.title,
                "kind": doc.kind,
                "owner": doc.owner,
                "updatedAt": doc.updated_at,
                "updatedAtLabel": format_date(doc.updated_at),
                "expiresAt": doc.expires_at,
                "status": doc.status,
                "summary": doc.summary,
                "passageCount": len(doc.passages),
                "sourceUrl": doc.source_url,
                "freshness": assess_freshness(doc, today).label,
            }
            for doc in CORPUS
        ],
    }


# ---------------------------------------------------------------------- #
# Static frontend                                                     #
# ---------------------------------------------------------------------- #

if FRONTEND_DIR.exists():
    app.mount(
        "/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static"
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        """Serve the single-page app for any non-API route."""
        candidate = FRONTEND_DIR / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")


def run() -> None:
    """Entry point for `python -m app` or `uvicorn app.main:app`."""
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)
