# FocusFlow AI

FocusFlow AI is an open-source productivity operations agent powered by **Gemma 4**. It converts a messy workload into an executable plan, then performs approved actions: Google Calendar creation, Gmail sending, and PowerPoint/PDF/Word generation.

## Why it fits PS03

This is an execution agent, not a single-response chatbot. Gemma 4 turns unstructured instructions into structured tasks and requested actions. The app orchestrates these tools:

1. `extract_tasks_with_gemma` turns natural language into validated task and action data.
2. `create_action_plan` transparently prioritizes and schedules work.
3. `replan` moves incomplete work forward after a disruption.
4. `create_calendar_events` creates Google Calendar events after explicit user approval.
5. `send_email` sends a reviewed Gmail draft after explicit user approval.
6. `create_pptx`, `create_pdf`, and `create_docx` generate local deliverables on demand.

Gemma 4 is the open model that understands the user's request and selects relevant actions. The user reviews every external action before it runs.

## Architecture

```text
Browser UI (HTML / CSS / JavaScript)
            |
            v
         Flask API
            |
            v
  Gemma 4 via Gemini API --> tasks and requested actions
            |
            v
  Local agent tools --> scheduling, SQLite, PDF, DOCX, PPTX
            |
            +--> approved Gmail send
            +--> approved Google Calendar creation
            +--> approved local file downloads
```

## Run locally

Prerequisites: Python 3.10+ and a Google AI Studio API key with Gemma 4 access.

```powershell
cd D:\Hack_day
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your GEMINI_API_KEY to .env
python app.py
```

Open `http://127.0.0.1:5000`. This project uses Flask plus plain HTML/CSS/JavaScript, not Streamlit.

## Enable Gmail and Google Calendar execution

Your Gemini API key cannot access private Google account data. Gmail and Google Calendar use Google OAuth and your consent.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable **Gmail API** and **Google Calendar API**.
3. Configure the OAuth consent screen. For testing with an External audience, add your own Google account as a test user.
4. Create an OAuth client: **Google Auth platform -> Clients -> Create client -> Web application**.
5. Add this exact authorized redirect URI:

   ```text
   http://127.0.0.1:5000/auth/google/callback
   ```

6. Download the OAuth client JSON and save it as `D:\Hack_day\credentials.json`.
7. Restart the app, then choose **Connect Google** in the execution panel. Sign in and approve Calendar-event and Gmail-send permissions.

`credentials.json` and the generated `token.json` are ignored by Git. Never commit either file. Google documents the same OAuth setup pattern in its [Gmail API Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python).

## Demo script

1. Enter: "Finish my Python project by Friday, prepare 10 slides, email my mentor a status update, and create calendar blocks. I have two hours today."
2. Show Gemma extracting tasks, deadlines, an email draft, and the execution requests.
3. Show the transparent priority score and daily focus blocks.
4. Review/edit the email and show the separate confirmation before sending it.
5. Approve Calendar event creation and generate a PowerPoint or PDF execution brief.
6. Mark a task as missed and use **Replan incomplete work**.

## Responsible use and limitations

- API keys remain in `.env`, which is ignored by Git.
- OAuth client and token files remain local and are ignored by Git.
- Task plans are saved to local SQLite storage.
- Model-estimated deadlines, recipients, and generated text must be reviewed.
- Gmail and Calendar operations need a separate, explicit confirmation in the browser.
- This MVP executes the included tools. More external actions can be added through the same approval-gated tool pattern.

## License

MIT. See [LICENSE](LICENSE).
