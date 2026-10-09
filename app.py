"""Flask server for FocusFlow AI."""

from __future__ import annotations

import os
from datetime import date
from io import BytesIO
from typing import Any

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, session, url_for

from artifacts import create_docx, create_pdf, create_pptx

from core import (
    build_plan,
    checklist_markdown,
    extract_tasks_with_gemma,
    get_plan,
    init_db,
    list_plans,
    plan_to_ics,
    replan,
    save_plan,
)
from google_actions import (
    GoogleAuthRequired,
    complete_authorization,
    configured as google_configured,
    connected as google_connected,
    create_calendar_events,
    get_authorization_url,
    send_email,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "focusflow-local-development-only")
init_db()


def payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Send a JSON request body.")
    return data


def read_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a date in YYYY-MM-DD format.") from error


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/health")
def health() -> Response:
    return jsonify({"status": "ok"})


@app.get("/api/google/status")
def google_status() -> Response:
    return jsonify({"configured": google_configured(), "connected": google_connected()})


@app.get("/auth/google/connect")
def google_connect():
    redirect_uri = url_for("google_callback", _external=True)
    try:
        authorization_url, state = get_authorization_url(redirect_uri)
    except GoogleAuthRequired as error:
        return redirect(url_for("index", auth_error=str(error)))
    session["google_oauth_state"] = state
    return redirect(authorization_url)


@app.get("/auth/google/callback")
def google_callback():
    if request.args.get("error"):
        return redirect(url_for("index", auth_error="Google authorization was cancelled."))
    state = session.pop("google_oauth_state", "")
    if not state or state != request.args.get("state"):
        return redirect(url_for("index", auth_error="Google authorization state could not be verified."))
    try:
        complete_authorization(request.url, state, url_for("google_callback", _external=True))
        return redirect(url_for("index", google_connected="1"))
    except Exception:
        return redirect(url_for("index", auth_error="Google account connection failed. Check your OAuth setup and try again."))


@app.get("/api/plans")
def plans() -> Response:
    return jsonify({"plans": list_plans()})


@app.get("/api/plans/<plan_id>")
def load_plan(plan_id: str) -> Response:
    plan = get_plan(plan_id)
    if not plan:
        return jsonify({"error": "Plan not found."}), 404
    return jsonify({"plan": plan})


@app.post("/api/plans")
def create_plan() -> Response:
    try:
        data = payload()
        user_request = str(data.get("request", "")).strip()
        if not user_request:
            raise ValueError("Describe your workload first.")
        hours = float(data.get("hours_per_day", 2))
        if not 0.5 <= hours <= 12:
            raise ValueError("Hours available per day must be between 0.5 and 12.")
        start_day = read_date(data.get("plan_start", date.today().isoformat()), "Plan start")
        extracted = extract_tasks_with_gemma(user_request, start_day)
        plan = build_plan(extracted, hours, start_day)
        plan["plan_id"] = save_plan(" ".join(user_request.split())[:55], user_request, plan)
        return jsonify({"plan": plan}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 502


@app.post("/api/replan")
def replan_work() -> Response:
    try:
        data = payload()
        plan = data.get("plan")
        missed_ids = data.get("missed_ids", [])
        if not isinstance(plan, dict) or not isinstance(missed_ids, list):
            raise ValueError("Plan data and missed task IDs are required.")
        restart_day = read_date(data.get("restart_day"), "Restart date")
        updated = replan(plan, {str(task_id) for task_id in missed_ids}, restart_day)
        updated["plan_id"] = save_plan("Replanned work", "Replanned from a saved plan", updated)
        return jsonify({"plan": updated})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/exports/calendar")
def calendar_export() -> Response:
    try:
        data = payload()
        schedule = data.get("schedule")
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("A non-empty schedule is required.")
        return send_file(
            BytesIO(plan_to_ics(schedule)),
            mimetype="text/calendar",
            as_attachment=True,
            download_name="focusflow-plan.ics",
        )
    except (ValueError, KeyError, TypeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/exports/checklist")
def checklist_export() -> Response:
    try:
        data = payload()
        plan = data.get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("schedule"), list):
            raise ValueError("A plan with a schedule is required.")
        return Response(
            checklist_markdown(plan),
            mimetype="text/markdown",
            headers={"Content-Disposition": "attachment; filename=focusflow-checklist.md"},
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/actions/calendar")
def execute_calendar() -> Response:
    try:
        data = payload()
        schedule = data.get("schedule")
        if data.get("approved") is not True:
            raise ValueError("Calendar creation needs explicit approval.")
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("A non-empty schedule is required.")
        return jsonify({"created": create_calendar_events(schedule)})
    except GoogleAuthRequired as error:
        return jsonify({"error": str(error), "connect_required": True}), 401
    except (ValueError, KeyError, TypeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/actions/email")
def execute_email() -> Response:
    try:
        data = payload()
        if data.get("approved") is not True:
            raise ValueError("Sending email needs explicit approval.")
        message_id = send_email(
            str(data.get("recipient", "")).strip(),
            str(data.get("subject", "")).strip(),
            str(data.get("body", "")).strip(),
        )
        return jsonify({"message_id": message_id})
    except GoogleAuthRequired as error:
        return jsonify({"error": str(error), "connect_required": True}), 401
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/actions/document")
def execute_document() -> Response:
    try:
        data = payload()
        plan = data.get("plan")
        kind = str(data.get("kind", "")).lower()
        if data.get("approved") is not True:
            raise ValueError("File generation needs explicit approval.")
        if not isinstance(plan, dict) or not isinstance(plan.get("schedule"), list):
            raise ValueError("A plan with a schedule is required.")
        files = {
            "pptx": (create_pptx, "focusflow-execution-plan.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            "pdf": (create_pdf, "focusflow-execution-brief.pdf", "application/pdf"),
            "docx": (create_docx, "focusflow-execution-report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        if kind not in files:
            raise ValueError("Unsupported file type.")
        generator, filename, mimetype = files[kind]
        return send_file(BytesIO(generator(plan)), mimetype=mimetype, as_attachment=True, download_name=filename)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
