# System diagram — CourseWise

Boxes and arrows only. Short labels. No paragraphs inside the diagram — the
brief counts words inside figures, so every label here is deliberately terse.

Render any block with a Mermaid renderer (GitHub renders Mermaid natively in
`.md` files, mermaid.live, or the VS Code Mermaid extension), or redraw it in
Lucidchart / draw.io using the same labels.

## Legend

| Label | Meaning |
| --- | --- |
| `IMPLEMENTED` | Working code in the submitted commit |
| `SIMULATED` | Interaction is shown, but the backing service is stubbed or local-only |
| `PLANNED` | Designed but not built |

## Figure 1 — System architecture

```mermaid
flowchart TB
    subgraph U["User"]
        U1["Student<br/>asks a question"]
        U2["Student<br/>confirms / cancels"]
    end

    subgraph FE["Frontend · IMPLEMENTED"]
        F1["index.html<br/>styles.css"]
        F2["app.js<br/>renders thread"]
        F3["Evidence panel<br/>cited / superseded badges"]
        F4["Conversation list<br/>+ bookings"]
    end

    subgraph API["FastAPI · IMPLEMENTED"]
        A1["POST /api/ask"]
        A2["POST /api/actions/id/confirm"]
        A3["POST /api/actions/id/cancel"]
        A4["GET /api/documents<br/>/api/slots /api/bookings"]
        A5["GET POST DELETE<br/>/api/conversations"]
        A6["GET /api/health"]
    end

    subgraph ORCH["Orchestrator · IMPLEMENTED"]
        O1["Intent detection<br/>question vs. state change"]
        O2["Sufficiency gate"]
        O3["Freshness + conflict"]
        O4["Prefer version in force"]
        O5["Answer assembly"]
    end

    subgraph RET["Retrieval · IMPLEMENTED"]
        R1["BM25 over passages"]
        R2["Synonym expansion<br/>weight 0.35"]
        R3["Strong synonyms<br/>weight 1.0"]
        R4["Light stemmer"]
        R5["Qualified-name<br/>phrase match"]
        R6["Current-version boost"]
    end

    subgraph POL["Policy · IMPLEMENTED"]
        P1["Freshness<br/>current / expiring / expired<br/>superseded / archived"]
        P2["Conflict detection<br/>value + unit"]
        P3["Coverage scoring<br/>IDF-weighted"]
    end

    subgraph GEN["Generation"]
        G1["Extractive<br/>sentence selection<br/>IMPLEMENTED · default"]
        G2["DeepSeek chat<br/>OpenAI-compatible API<br/>IMPLEMENTED · needs key"]
        G3["Claude<br/>SIMULATED · needs key"]
    end

    subgraph ACT["Actions · IMPLEMENTED"]
        T1["propose()"]
        T2["pending action<br/>preview + fields + consequence"]
        T3["commit() / cancel()"]
        T4["single-use action id"]
    end

    subgraph DB["SQLite · IMPLEMENTED"]
        C1["documents + passages<br/>12 versions"]
        C2["conversations + messages"]
        C3["slots + bookings"]
        C4["pending_actions"]
    end

    subgraph CFG["Config · IMPLEMENTED"]
        CF1[".env loader<br/>envfile.py"]
        CF2["409 on locked DB"]
    end

    U1 --> F1 --> F2 --> A1
    F2 --> A4
    F2 --> A5
    F2 --> A6
    A1 --> O1
    O1 -->|"state change"| T1
    O1 -->|"question"| O2
    O2 --> RET
    O2 --> P3
    O3 --> P1
    O3 --> P2
    RET --> C1
    O4 -->|"supported"| GEN
    O4 -->|"insufficient"| O5
    GEN --> O5
    O5 --> F3
    T1 --> T2
    T2 --> F3
    T4 --> T2
    F3 --> U2
    U2 --> A2
    U2 --> A3
    A2 --> T3
    A3 --> T3
    T3 --> C3
    T3 --> C4
    A5 --> C2
    A1 --> C2
    CF1 --> GEN
    CF2 --> API
```

## Figure 2 — Answer path (control and AI behaviour)

```mermaid
sequenceDiagram
    participant S as Student
    participant UI as Frontend
    participant API as FastAPI
    participant O as Orchestrator
    participant R as Retrieval
    participant P as Policy
    participant G as Generation

    S->>UI: "final exam format?"
    UI->>API: POST /api/ask
    API->>O: handle(question, history)
    O->>R: retrieve(question)
    R->>R: expand, stem, phrase match,<br/>version boost
    R-->>O: ranked passages
    O->>P: freshness / conflicts / coverage
    P-->>O: warnings, sufficiency
    alt coverage sufficient
        O->>G: answer from current passages
        G-->>O: text + cited passage ids
    else coverage insufficient
        O->>G: refuse, name missing detail
        G-->>O: refusal text
    end
    Note over G: system prompt —<br/>cite [n] inline<br/>refuse if evidence gap<br/>ignore superseded values<br/>max 120 words
    O-->>API: status, answer, sources, warnings
    API-->>UI: JSON payload
    UI-->>S: answer + evidence panel
```

## Figure 3 — State change path (two-phase)

```mermaid
flowchart TB
    Q["Student:<br/>'book me a slot'"] --> M{"Intent<br/>action?"}
    M -->|"no"| ANS["Answer path<br/>Figure 2"]
    M -->|"yes"| SL["Match free slot<br/>date / time / tutor"]
    SL -->|"no free slot"| UN["action-unavailable<br/>nothing changed"]
    SL --> P["propose()"]
    P --> PV["Preview card<br/>date · time · tutor · topic<br/>+ consequence + cancel rule"]
    PV -->|"confirm + action id"| C["commit()"]
    PV -->|"cancel"| X["discard<br/>nothing written"]
    C -->|"id already used"| E["409 rejected<br/>single-use id"]
    C --> B["Booking written<br/>SQLite bookings"]
    X --> N["State unchanged"]
    B -.->|"PLANNED"| EM["Email notification<br/>no mail service"]
```

The assistant can only ever reach `propose()`. The `commit()` branch is
reachable only by an explicit `POST /api/actions/{id}/confirm` carrying the
action id, and each action can be committed at most once.

## Figure 4 — Document version tree

```mermaid
flowchart TB
    subgraph R1[" "]
    direction LR
      subgraph K1["assignment-1-brief"]
        direction TB
        K1a["v1 · 14 Sep<br/>SUPERSEDED"] --> K1b["v2 · 28 Sep<br/>CURRENT"]
      end
      subgraph K3["exam-format"]
        direction TB
        K3a["v1 · 10 Sep<br/>SUPERSEDED"] --> K3b["v2 · 1 Oct<br/>CURRENT"]
      end
      subgraph K4["plagiarism-policy"]
        direction TB
        K4a["v1 · 1 Sep<br/>ARCHIVED"] --> K4b["v2 · 15 Oct<br/>CURRENT"]
      end
    end
    subgraph R2[" "]
    direction LR
      subgraph K2["assignment-2-brief"]
        direction TB
        K2a["v1 · 20 Oct<br/>CURRENT"]
      end
      subgraph K5["module-faq"]
        direction TB
        K5a["v1 · 20 Oct<br/>CURRENT"]
      end
      subgraph K6["module-timeline"]
        direction TB
        K6a["v1 · 12 Oct<br/>CURRENT"]
      end
    end
    subgraph R3[" "]
    direction LR
      subgraph K7["office-hours"]
        direction TB
        K7a["v1 · 18 Oct<br/>CURRENT"]
      end
      subgraph K8["reading-list"]
        direction TB
        K8a["v1 · 5 Oct<br/>CURRENT"]
      end
      subgraph K9["room-booking"]
        direction TB
        K9a["v1 · 25 Sep<br/>CURRENT"]
      end
    end
```

Nine document keys, twelve versions: three keys carry a superseded or
archived predecessor, so version resolution and conflict detection have
something to resolve.
