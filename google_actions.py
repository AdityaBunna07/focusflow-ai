"""Explicitly approved Google Calendar and Gmail actions for FocusFlow."""

from __future__ import annotations

import base64
import os
from datetime import date, datetime, time, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

APP_DIR = Path(__file__).parent
CLIENT_FILE = Path(os.getenv("GOOGLE_OAUTH_CLIENT_FILE", APP_DIR / "credentials.json"))
TOKEN_FILE = Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", APP_DIR / "token.json"))
TIMEZONE = os.getenv("FOCUSFLOW_TIMEZONE", "Asia/Kolkata")
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
]


class GoogleAuthRequired(RuntimeError):
    pass


def configured() -> bool:
    return CLIENT_FILE.is_file()


def connected() -> bool:
    return TOKEN_FILE.is_file()


def get_authorization_url(redirect_uri: str) -> tuple[str, str]:
    if not configured():
        raise GoogleAuthRequired("Google OAuth is not configured. Add credentials.json first.")
    flow = Flow.from_client_secrets_file(CLIENT_FILE, scopes=SCOPES, redirect_uri=redirect_uri)
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    return authorization_url, state


def complete_authorization(authorization_response: str, state: str, redirect_uri: str) -> None:
    flow = Flow.from_client_secrets_file(CLIENT_FILE, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
    flow.fetch_token(authorization_response=authorization_response)
    TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")


def credentials() -> Credentials:
    if not connected():
        raise GoogleAuthRequired("Connect your Google account before executing Gmail or Calendar actions.")
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GoogleAuthRequired("Your Google connection expired. Connect again to continue.")
    return creds


def create_calendar_events(schedule: list[dict[str, Any]]) -> list[dict[str, str]]:
    service = build("calendar", "v3", credentials=credentials())
    created = []
    for item in schedule:
        start = datetime.combine(date.fromisoformat(item["scheduled_date"]), time(9, 0))
        end = start + timedelta(minutes=int(item["estimated_minutes"]))
        event = service.events().insert(
            calendarId="primary",
            body={
                "summary": f"FocusFlow: {item['title']}",
                "description": item.get("notes", "") or "Created after FocusFlow approval.",
                "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
                "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
            },
        ).execute()
        created.append({"id": event["id"], "htmlLink": event.get("htmlLink", "")})
    return created


def send_email(recipient: str, subject: str, body: str) -> str:
    if not recipient or "@" not in recipient:
        raise ValueError("Enter a valid recipient email address before sending.")
    if not subject.strip() or not body.strip():
        raise ValueError("An email subject and body are required.")
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = recipient
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = build("gmail", "v1", credentials=credentials()).users().messages().send(userId="me", body={"raw": raw}).execute()
    return result["id"]
