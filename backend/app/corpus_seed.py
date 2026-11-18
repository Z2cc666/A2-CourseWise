"""Seed data for the course document corpus.

This is the authoring source. On first run it is inserted into SQLite by
``app.db.ensure_seeded``; after that the database holds the corpus and this
module is only the initialiser.

Every document is a *versioned* unit of course evidence. ``doc_key`` groups
versions of the same logical artefact (for example ``assignment-1-brief``).
``status`` records whether the version is the one currently in force.

The corpus deliberately contains:

* superseded versions, so the system can find and flag stale evidence
* conflicting values across versions (two different submission dates)
* documents with no successor, so "this is the only version" is meaningful
* topics that are simply absent, so the system can refuse honestly
"""

from __future__ import annotations

from .models import MODULE, CourseDoc, DocKind, DocStatus, Passage


def _p(pid: str, heading: str, text: str) -> Passage:
    return Passage(id=pid, heading=heading, text=text)


SEED_CORPUS: tuple[CourseDoc, ...] = (
    # ------------------------------------------------------------------ #
    # Assignment 1 brief — v1 superseded, v2 current, values conflict.     #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="a1-brief-v1",
        doc_key="assignment-1-brief",
        title="Assignment 1 Brief — Reflective Journal",
        kind="assessment",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-09-14",
        status="superseded",
        summary=(
            "Original brief for Assignment 1. Replaced on 2026-09-28 when the "
            "weighting and word limit were revised."
        ),
        applies_to=("Week 1", "Week 2"),
        source_url="https://canvas.bham.ac.uk/courses/90253/assignments/633300",
        passages=(
            _p(
                "a1-brief-v1-p1",
                "Task and weighting",
                "Assignment 1 is a reflective journal of 1200 words. It accounts for "
                "30% of the module mark. Submit as a single PDF through Canvas "
                "before the deadline.",
            ),
            _p(
                "a1-brief-v1-p2",
                "Submission deadline",
                "The submission deadline for Assignment 1 is Friday 16 October 2026 "
                "at 21:00. Late submissions are penalised at 10% per day.",
            ),
            _p(
                "a1-brief-v1-p3",
                "Referencing",
                "Use Harvard referencing. At least eight academic sources are "
                "required, drawn from peer-reviewed journals published within the "
                "last five years.",
            ),
        ),
    ),
    CourseDoc(
        id="a1-brief-v2",
        doc_key="assignment-1-brief",
        title="Assignment 1 Brief — Reflective Journal",
        kind="assessment",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-09-28",
        status="current",
        summary=(
            "Current Assignment 1 brief. Weighting revised to 25% and word limit "
            "reduced to 1000 words."
        ),
        applies_to=("Week 1", "Week 2", "Week 3"),
        source_url="https://canvas.bham.ac.uk/courses/90253/assignments/633300",
        passages=(
            _p(
                "a1-brief-v2-p1",
                "Task and weighting",
                "Assignment 1 is a reflective journal of 1000 words. It accounts for "
                "25% of the module mark. Submit as a single PDF through Canvas "
                "before the deadline. The weighting was revised down from 30% "
                "after the mid-module review.",
            ),
            _p(
                "a1-brief-v2-p2",
                "Submission deadline",
                "The submission deadline for Assignment 1 is Friday 30 October 2026 "
                "at 21:00. This date supersedes the earlier 16 October date. Late "
                "submissions are penalised at 10% per day.",
            ),
            _p(
                "a1-brief-v2-p3",
                "Referencing",
                "Use Harvard referencing. At least six academic sources are "
                "required, drawn from peer-reviewed journals published within the "
                "last five years. The minimum source count was reduced from eight "
                "after student feedback in Week 2.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Assignment 2 brief — the current assignment itself.                 #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="a2-brief-v1",
        doc_key="assignment-2-brief",
        title="Assignment 2 Brief — Project Report",
        kind="assessment",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-20",
        status="current",
        summary=(
            "Current Assignment 2 brief: project report, 100 points, word limits "
            "and submission format."
        ),
        applies_to=("Week 1", "Week 2", "Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/assignments/633325",
        passages=(
            _p(
                "a2-brief-v1-p1",
                "What the assignment asks for",
                "Make your intelligent interactive system and show how someone "
                "interacts with it. Explain what you made, why you made those "
                "choices and how the work developed. Choose a scope that suits the "
                "complexity of your project.",
            ),
            _p(
                "a2-brief-v1-p2",
                "Report sections and word limits",
                "The report must contain an abstract of up to 300 words and a "
                "design rationale and project explanation of around 1000 words, "
                "with a maximum of 1100 words. The abstract and main report "
                "together must not exceed 1400 words. Figures, diagrams, "
                "storyboards, references and README content are outside the word "
                "limit.",
            ),
            _p(
                "a2-brief-v1-p3",
                "Required components",
                "The report must include a system diagram showing components, "
                "connections and information or control flows including AI "
                "behaviour, with implemented, simulated and planned elements "
                "clearly labelled. It must also include storyboards or illustrated "
                "interaction showing two or three examples of use, and links to a "
                "public GitHub repository and README with a development record.",
            ),
            _p(
                "a2-brief-v1-p4",
                "Submission and deadline",
                "Submit one project report containing links to the repository and "
                "README. Submit an accompanying ZIP only for material that cannot "
                "reasonably go in the repository. The deadline is Friday 20 "
                "November 2026 at 21:00. No video is required.",
            ),
            _p(
                "a2-brief-v1-p5",
                "What counts as developed work",
                "You may show an implementation, prototype, simulation or a "
                "walkthrough of developed screens and states. Clearly label "
                "placeholders, including hardware you could not develop, and "
                "explain what they represent. Visual polish and the number of "
                "features are not a priority.",
            ),
            _p(
                "a2-brief-v1-p6",
                "Use of AI",
                "You may use AI to help develop the system and prepare the report, "
                "diagrams, storyboards and README. You are responsible for the "
                "design choices, claims and references you submit. Briefly record "
                "how you used AI in the README, including what you checked or "
                "changed.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Plagiarism policy — older version with a looser rule.                #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="plagiarism-v1",
        doc_key="plagiarism-policy",
        title="Plagiarism and Generative AI Policy",
        kind="policy",
        owner="Academic Integrity Office",
        authored_by="Academic Integrity Office",
        updated_at="2026-09-01",
        expires_at="2026-10-15",
        status="archived",
        summary=(
            "Superseded version of the integrity policy. Replaced in October with "
            "stricter rules on AI-generated text."
        ),
        applies_to=("Week 1", "Week 2"),
        source_url="https://www.birmingham.ac.uk/students/academic-integrity",
        passages=(
            _p(
                "plagiarism-v1-p1",
                "Generative AI use",
                "Generative AI tools may be used to support research and "
                "understanding. Where AI is used, students should check the output "
                "for factual accuracy before relying on it. AI assistance is "
                "permitted where it is declared.",
            ),
            _p(
                "plagiarism-v1-p2",
                "Penalties",
                "Undeclared use of generative AI may lead to a mark of zero for the "
                "assessed component and referral to the academic integrity panel.",
            ),
        ),
    ),
    CourseDoc(
        id="plagiarism-v2",
        doc_key="plagiarism-policy",
        title="Plagiarism and Generative AI Policy",
        kind="policy",
        owner="Academic Integrity Office",
        authored_by="Academic Integrity Office",
        updated_at="2026-10-15",
        status="current",
        summary=(
            "Current integrity policy, updated October 2026. Tightens rules on "
            "AI-generated text and adds an AI declaration requirement."
        ),
        applies_to=("Week 1", "Week 2", "Week 3", "Week 4"),
        source_url="https://www.birmingham.ac.uk/students/academic-integrity",
        passages=(
            _p(
                "plagiarism-v2-p1",
                "Generative AI use",
                "Generative AI tools may be used to support research, understanding "
                "and drafting. AI-generated text must not be submitted as the "
                "student's own work. Where AI is used in assessed work, students "
                "must declare which tools were used, what they were asked to help "
                "with, and how the output was checked and corrected. Unedited AI "
                "output will be treated as unattributed third-party work.",
            ),
            _p(
                "plagiarism-v2-p2",
                "Penalties",
                "Undeclared use of generative AI in assessed work may lead to a mark "
                "of zero for the assessed component and referral to the academic "
                "integrity panel. This extends the earlier rule, which applied only "
                "to unattributed AI use.",
            ),
            _p(
                "plagiarism-v2-p3",
                "Checking AI output",
                "Students are responsible for verifying factual claims in AI "
                "output against authoritative sources before relying on them. "
                "Quoting or paraphrasing without checking is treated as negligence.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Timeline — current, rich source for questions about weeks.           #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="timeline-v1",
        doc_key="module-timeline",
        title="Module Teaching Timeline",
        kind="schedule",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-12",
        status="current",
        summary="Weekly schedule of sessions, topics and deadlines for the module.",
        applies_to=("Week 1", "Week 2", "Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/timeline",
        passages=(
            _p(
                "timeline-v1-p1",
                "Week 1",
                "Week 1 introduces human-centred design for intelligent systems: "
                "what makes an interface intelligent, and the difference between "
                "automation and augmentation. Seminar on Monday, lab on Wednesday.",
            ),
            _p(
                "timeline-v1-p2",
                "Week 2",
                "Week 2 covers conversation design and the design of AI "
                "interactions. Topics include turn-taking, repair, and handling "
                "uncertainty. Lab on Thursday this week.",
            ),
            _p(
                "timeline-v1-p3",
                "Week 3",
                "Week 3 focuses on trust, transparency and explainability in "
                "intelligent systems. Students are asked to complete Assignment 1 "
                "by Friday 30 October at 21:00.",
            ),
            _p(
                "timeline-v1-p4",
                "Week 4",
                "Week 4 addresses evaluation of intelligent systems: how to measure "
                "interaction quality, and how to test whether users trust a system "
                "appropriately. Assignment 2 is due Friday 20 November 2026 at "
                "21:00.",
            ),
            _p(
                "timeline-v1-p5",
                "Assessment overview",
                "There are two assessed components. Assignment 1, the reflective "
                "journal, is worth 25% of the final mark. Assignment 2, the project "
                "report, is worth 30% of the final mark. A final exam accounts for "
                "the remaining 45%.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Exam — stale version with an out-of-date value, newer version exists.#
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="exam-v1",
        doc_key="exam-format",
        title="Final Exam Format",
        kind="assessment",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-09-10",
        expires_at="2026-10-01",
        status="superseded",
        summary=(
            "Original exam format announcement, superseded in October when the "
            "question count changed."
        ),
        applies_to=("Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/exam",
        passages=(
            _p(
                "exam-v1-p1",
                "Exam structure",
                "The final exam is a 90-minute written paper consisting of three "
                "questions. Two questions are compulsory and one is optional.",
            ),
            _p(
                "exam-v1-p2",
                "Exam date",
                "The final exam takes place on Wednesday 9 December 2026 at 09:00 "
                "in the Great Hall.",
            ),
            _p(
                "exam-v1-p3",
                "Materials",
                "The exam is open book. Students may bring printed notes and one "
                "copy of the module handbook. Calculators are permitted.",
            ),
        ),
    ),
    CourseDoc(
        id="exam-v2",
        doc_key="exam-format",
        title="Final Exam Format",
        kind="assessment",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-01",
        status="current",
        summary=(
            "Current exam format. Question count increased to four and duration "
            "reduced to 60 minutes."
        ),
        applies_to=("Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/exam",
        passages=(
            _p(
                "exam-v2-p1",
                "Exam structure",
                "The final exam is a 60-minute written paper consisting of four "
                "questions. Two questions are compulsory and two are optional, with "
                "the higher scoring optional question counting. This replaces the "
                "earlier three-question format.",
            ),
            _p(
                "exam-v2-p2",
                "Exam date",
                "The final exam takes place on Wednesday 9 December 2026 at 09:00 "
                "in the Great Hall. The date is unchanged from the earlier "
                "announcement.",
            ),
            _p(
                "exam-v2-p3",
                "Materials",
                "The exam is open book. Students may bring printed notes and one "
                "copy of the module handbook. Calculators are permitted. Mobile "
                "phones are not permitted in the exam room.",
            ),
            _p(
                "exam-v2-p4",
                "Preparation guidance",
                "Prepare by practising the four question types shown in the Week 4 "
                "seminar. Credit is given for naming and applying specific design "
                "concepts rather than describing them generally.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Reading list — current, rich source for "recommended readings".      #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="readings-v1",
        doc_key="reading-list",
        title="Module Reading List",
        kind="resource",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-05",
        status="current",
        summary="Core and recommended readings, mapped to weeks.",
        applies_to=("Week 1", "Week 2", "Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/readings",
        passages=(
            _p(
                "readings-v1-p1",
                "Core reading on trust and transparency",
                "Parasuraman and Riley (1997) \"Humans and Automation: Use, Misuse, "
                "Disuse, Abuse\" distinguishes the use, misuse, disuse and abuse of "
                "automation, and remains the standard reference for explaining when "
                "trust in an automated system should be withheld. Also recommended: "
                "Jian et al. (2000) on trust and reliance in automation, and "
                "Dzindolet et al. (2003) on the role of perceived error in "
                "automation trust.",
            ),
            _p(
                "readings-v1-p2",
                "Core reading on explanation and trust repair",
                "Luo et al. (2009) and Kocijan et al. (2023) argue that "
                "explanations improve trust only when they are calibrated to the "
                "user's question and delivered at the point of decision. Kocijan, "
                "Miller and Parzen (2023) \"To Explain or Not to Explain: Articulating "
                "Design Rationales for Human-AI Interaction\" in CHI 2023 provides the "
                "clearest recent treatment of rationale articulation for intelligent "
                "systems.",
            ),
            _p(
                "readings-v1-p3",
                "Core reading on transparency and the illusion of understanding",
                "Siau and Wang (2018) on transparency in algorithmic "
                "decision-making, and Schmidt et al. (2023) \"How do people react to "
                "AI failure?\" in CHI 2023 on how users respond when an AI system "
                "makes a mistake, both bear directly on designing for graceful "
                "failure.",
            ),
            _p(
                "readings-v1-p4",
                "Recommended reading on conversational interfaces",
                "Aluidini and Shaffar (2018) \"The Harvard Business Review guide to "
                "conversational AI\" covers the commercial grounding of dialogue "
                "systems. For design practice, Follow (2019) and Gray et al. on "
                "prototyping AI features are useful.",
            ),
            _p(
                "readings-v1-p5",
                "Readings for the four taught weeks",
                "Week 1: automation and augmentation — Parasuraman and Riley (1997). "
                "Week 2: conversation design — Luger and Sellen (2016). Week 3: trust "
                "and transparency — Jian et al. (2000) and Siau and Wang (2018). "
                "Week 4: evaluation — Amershi et al. (2019) on guidelines for "
                "interaction design with AI systems.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # Office hours and support — the target of state-changing actions.    #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="support-v1",
        doc_key="office-hours",
        title="Consultation and Office Hours",
        kind="module-info",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-18",
        status="current",
        summary="How to book a consultation slot, and what preparation is expected.",
        applies_to=("Week 2", "Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/office-hours",
        passages=(
            _p(
                "support-v1-p1",
                "Booking a slot",
                "Consultation slots are 20 minutes and can be booked up to 48 hours in "
                "advance. Book through the module portal. Bookings are confirmed by "
                "email; a booking without a confirmation email has not been placed.",
            ),
            _p(
                "support-v1-p2",
                "What to bring",
                "Bring one specific question and your attempt at an answer. Students "
                "who have read the relevant section of the module handbook before the "
                "session are more likely to get a useful response.",
            ),
            _p(
                "support-v1-p3",
                "Cancellations",
                "Cancellations must be made at least 12 hours before the slot starts, "
                "otherwise the slot is recorded as missed. Cancelling and rebooking "
                "repeatedly may restrict access to consultation slots.",
            ),
            _p(
                "support-v1-p4",
                "Waiting list",
                "If no slot is available, join the waiting list. Slots that are "
                "released by cancellation are offered to the waiting list in order of "
                "joining.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # A document with no successor but an old date — tests "sole source".  #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="rooms-v1",
        doc_key="room-booking",
        title="Room Booking for Seminars",
        kind="module-info",
        owner="Estates Office",
        authored_by="Estates Office",
        updated_at="2026-09-25",
        status="current",
        summary="Seminar room allocations and how to request a room change.",
        applies_to=("Week 3",),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/rooms",
        passages=(
            _p(
                "rooms-v1-p1",
                "Allocated rooms",
                "Week 3 seminars are held in Room 104, Aston Webb Building. The "
                "seminar room has not changed since the start of term.",
            ),
            _p(
                "rooms-v1-p2",
                "Requesting a change",
                "Room change requests go to the Estates Office and are decided "
                "within three working days. Requests are not guaranteed.",
            ),
        ),
    ),
    # ------------------------------------------------------------------ #
    # FAQ with generic but genuinely relevant answers.                    #
    # ------------------------------------------------------------------ #
    CourseDoc(
        id="faq-v1",
        doc_key="module-faq",
        title="Module Frequently Asked Questions",
        kind="faq",
        owner="Module Teaching Team",
        authored_by="Module Teaching Team",
        updated_at="2026-10-20",
        status="current",
        summary="Common questions about submission, extensions, referencing and redaction.",
        applies_to=("Week 1", "Week 2", "Week 3", "Week 4"),
        source_url="https://canvas.bham.ac.uk/courses/90253/pages/faq",
        passages=(
            _p(
                "faq-v1-p1",
                "File formats",
                "Submit your report as PDF. Word documents are accepted but are "
                "converted, which can break layout. The file name should be your "
                "student number followed by the assignment name.",
            ),
            _p(
                "faq-v1-p2",
                "Extensions",
                "Extensions are granted only by the module leader and require "
                "supporting evidence such as a medical certificate. Extensions are "
                "not granted for assessment workload, work commitments or personal "
                "scheduling.",
            ),
            _p(
                "faq-v1-p3",
                "Referencing software",
                "Mendeley, Zotero and EndNote are all supported by the library. Any "
                "Harvard-compatible style is accepted. The library runs an "
                "introduction session in Week 1.",
            ),
            _p(
                "faq-v1-p4",
                "Redacting personal data",
                "Remove names and identifiers from any screenshots you include. Use "
                "the redaction tool in your PDF editor rather than covering text with "
                "a shape, since covered text can be recovered.",
            ),
            _p(
                "faq-v1-p5",
                "Working in a group",
                "Assignment 2 is an individual submission. You may discuss ideas "
                "with other students, but the report, the README and the code you "
                "submit must be your own work.",
            ),
            _p(
                "faq-v1-p6",
                "Using a real AI model",
                "It is acceptable to build your project on a hosted language model. "
                "You must record the model, the version and how the output was "
                "checked, and you must not include API keys in your repository.",
            ),
        ),
    ),
)
