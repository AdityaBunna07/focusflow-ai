"""Core tools for the FocusFlow productivity operations agent."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from ics import Calendar, Event

load_dotenv()

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "focusflow.db"
DEFAULT_MODEL = "gemma-4-26b-a4b-it"

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "clarifying_question": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "deadline": {"type": "string"},
                    "estimated_minutes": {"type": "integer"},
                    "importance": {"type": "integer"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "deadline", "estimated_minutes", "importance", "notes"],
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "recipient": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "details": {"type": "string"},
                },
                "required": ["type", "title", "recipient", "subject", "body", "details"],
            },
        },
    },
    "required": ["summary", "clarifying_question", "tasks", "actions"],
}

ALLOWED_ACTIONS = {"calendar", "email", "pptx", "pdf", "docx"}


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                raw_request TEXT NOT NULL,
                plan_json TEXT NOT NULL
            )
            """
        )


def save_plan(title: str, raw_request: str, plan: dict[str, Any]) -> str:
    plan_id = str(uuid4())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO plans VALUES (?, ?, ?, ?, ?)",
            (plan_id, datetime.now().isoformat(timespec="seconds"), title, raw_request, json.dumps(plan)),
        )
    return plan_id


def list_plans() -> list[dict[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, created_at, title FROM plans ORDER BY created_at DESC"
        ).fetchall()
    return [{"id": row[0], "created_at": row[1], "title": row[2]} for row in rows]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT plan_json FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return json.loads(row[0]) if row else None


def get_client():
    """Create the Gemini client only when a request is actually made."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY. Copy .env.example to .env and add your key.")
    from google import genai

    return genai.Client(api_key=api_key)


def normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for raw in data.get("tasks", []):
        title = str(raw.get("title", "Untitled task")).strip()
        if not title:
            continue
        deadline = str(raw.get("deadline", "")).strip()
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                deadline = ""
        try:
            minutes = int(raw.get("estimated_minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        try:
            importance = int(raw.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        tasks.append(
            {
                "id": str(uuid4())[:8],
                "title": title[:180],
                "deadline": deadline,
                "estimated_minutes": max(15, min(minutes, 960)),
                "importance": max(1, min(importance, 5)),
                "notes": str(raw.get("notes", "")).strip()[:500],
                "status": "planned",
            }
        )
    if not tasks:
        raise RuntimeError("No actionable tasks were identified. Please describe what you need to do.")

    actions = []
    for raw in data.get("actions", []):
        action_type = str(raw.get("type", "")).strip().lower()
        if action_type not in ALLOWED_ACTIONS:
            continue
        actions.append(
            {
                "type": action_type,
                "title": str(raw.get("title", action_type.title())).strip()[:160],
                "recipient": str(raw.get("recipient", "")).strip()[:254],
                "subject": str(raw.get("subject", "")).strip()[:250],
                "body": str(raw.get("body", "")).strip()[:6000],
                "details": str(raw.get("details", "")).strip()[:500],
            }
        )
    return {
        "summary": str(data.get("summary", "Tasks extracted from your request.")).strip(),
        "clarifying_question": str(data.get("clarifying_question", "")).strip(),
        "tasks": tasks,
        "actions": actions,
    }


def extract_tasks_with_gemma(user_request: str, today: date) -> dict[str, Any]:
    """Tool 1: turn an unstructured workload into reliable task data."""
    from google.genai import types

    prompt = f"""
You are FocusFlow's task-understanding agent. Today is {today.isoformat()}.
Read the user's messy productivity request and extract only actionable tasks.
Infer a sensible duration only when it is missing. importance is 1 (low) to 5 (critical).
Use an ISO date (YYYY-MM-DD) for deadline, or an empty string when unknown.
Never invent a specific deadline. Ask at most one concise clarifying question only if it
would materially change prioritization. Return JSON matching the supplied schema.

Also identify actions the user explicitly asks FocusFlow to perform. Allowed action types are:
calendar (create events for the task plan), email (draft an email), pptx (create a slide deck),
pdf (create a PDF brief), and docx (create a Word report). Do not infer an action merely because
it might be useful. For email, never invent a recipient email address: use an empty recipient if
one was not supplied. Draft a useful subject and body only when an email action was requested.

User request:
{user_request}
"""
    client = get_client()
    response = client.models.generate_content(
        model=os.getenv("GEMMA_MODEL", DEFAULT_MODEL),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=TASK_SCHEMA,
            temperature=0.2,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemma returned an empty response. Please try again.")
    return normalize_extraction(json.loads(response.text))


def urgency(task: dict[str, Any], start_day: date) -> int:
    if not task["deadline"]:
        return 1
    days = (date.fromisoformat(task["deadline"]) - start_day).days
    if days <= 0:
        return 5
    if days == 1:
        return 4
    if days <= 3:
        return 3
    if days <= 7:
        return 2
    return 1


def priority_score(task: dict[str, Any], start_day: date) -> int:
    quick_win = 1 if task["estimated_minutes"] <= 60 else 0
    return urgency(task, start_day) * 3 + task["importance"] * 2 + quick_win


def create_action_plan(tasks: list[dict[str, Any]], hours_per_day: float, start_day: date) -> list[dict[str, Any]]:
    """Tool 2: schedule tasks with an explainable local planner."""
    capacity = max(30, int(hours_per_day * 60))
    pending = sorted(tasks, key=lambda task: (-priority_score(task, start_day), task["deadline"] or "9999-12-31"))
    schedule: list[dict[str, Any]] = []
    day = start_day
    minutes_left = capacity
    while pending:
        task = pending.pop(0).copy()
        required = task["estimated_minutes"]
        if required <= minutes_left:
            task["scheduled_date"] = day.isoformat()
            task["priority_score"] = priority_score(task, start_day)
            schedule.append(task)
            minutes_left -= required
        else:
            block_minutes = min(minutes_left, 90) if minutes_left >= 30 else 0
            if block_minutes:
                block = task.copy()
                block["title"] = f"{task['title']} — focus block"
                block["estimated_minutes"] = block_minutes
                block["scheduled_date"] = day.isoformat()
                block["priority_score"] = priority_score(task, start_day)
                block["parent_id"] = task["id"]
                schedule.append(block)
                task["estimated_minutes"] -= block_minutes
                minutes_left -= block_minutes
            if task["estimated_minutes"] > 0:
                pending.insert(0, task)
        if minutes_left < 30:
            day += timedelta(days=1)
            minutes_left = capacity
        if len(schedule) > 120:
            raise RuntimeError("Plan is too large. Please submit a smaller set of tasks.")
    return schedule


def build_plan(extracted: dict[str, Any], hours_per_day: float, start_day: date) -> dict[str, Any]:
    return {
        "summary": extracted["summary"],
        "clarifying_question": extracted["clarifying_question"],
        "hours_per_day": hours_per_day,
        "created_for": start_day.isoformat(),
        "tasks": extracted["tasks"],
        "actions": extracted.get("actions", []),
        "schedule": create_action_plan(extracted["tasks"], hours_per_day, start_day),
    }


def replan(plan: dict[str, Any], missed_ids: set[str], restart_day: date) -> dict[str, Any]:
    """Tool 3: move incomplete work forward without silently dropping it."""
    remaining = []
    for task in plan["tasks"]:
        if task["id"] in missed_ids:
            copy = task.copy()
            copy["status"] = "rescheduled"
            remaining.append(copy)
    if not remaining:
        raise RuntimeError("Select at least one incomplete task to replan.")
    updated = plan.copy()
    updated["schedule"] = create_action_plan(remaining, float(plan["hours_per_day"]), restart_day)
    updated["replanned_on"] = restart_day.isoformat()
    return updated


def plan_to_ics(schedule: list[dict[str, Any]]) -> bytes:
    """Tool 4: create a local calendar file only after user approval."""
    calendar = Calendar()
    for item in schedule:
        event = Event()
        event.name = f"FocusFlow: {item['title']}"
        event.begin = datetime.combine(date.fromisoformat(item["scheduled_date"]), time(9, 0))
        event.duration = timedelta(minutes=int(item["estimated_minutes"]))
        event.description = item.get("notes", "") or "FocusFlow planned task"
        calendar.events.add(event)
    return calendar.serialize().encode("utf-8")


def checklist_markdown(plan: dict[str, Any]) -> str:
    lines = ["# FocusFlow checklist", ""]
    for item in plan["schedule"]:
        deadline = f" · due {item['deadline']}" if item.get("deadline") else ""
        lines.append(f"- [ ] {item['scheduled_date']}: {item['title']} ({item['estimated_minutes']} min){deadline}")
    return "\n".join(lines)
