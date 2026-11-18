"""Consultation slots published by the module team.

Kept in its own module so that both the database seeder and the action
store can read the list without importing each other.
"""

from __future__ import annotations

#: Slots the module team publishes for consultations.
AVAILABLE_SLOTS: tuple[dict[str, str], ...] = (
    {"date": "2026-11-10", "time": "10:00", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-10", "time": "14:30", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-11", "time": "11:00", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-11", "time": "15:00", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-12", "time": "09:30", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-12", "time": "15:30", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-13", "time": "13:00", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-13", "time": "16:00", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-16", "time": "10:00", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-16", "time": "14:00", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-17", "time": "11:30", "tutor": "Dr A. Rahman"},
    {"date": "2026-11-18", "time": "14:00", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-19", "time": "10:30", "tutor": "Prof. L. Chen"},
    {"date": "2026-11-19", "time": "15:00", "tutor": "Prof. L. Chen"},
)
