# 🧠 Multi-Agent Task Automation System

An intelligent task automation assistant powered by multiple agents and AI services. This app enables you to create calendar events, send Slack messages, perform web searches, consult a local knowledge base, and interact via Twilio, all using natural language commands.

---

## 📁 Project Structure

```
Multi-Agent-App/
│
├── static/              # Contains index.html frontend
├── knowledge_base/      # Stores .txt knowledge files
├── agents.py            # All agent classes (Slack, Calendar, Twilio, etc.)
├── main.py              # FastAPI entrypoint
├── orchestrator.py      # Task orchestration logic
├── retry.py             # Retry policy for outbound API calls
├── eval/                # Planner evaluation and failure injection
├── tests/               # pytest suite
├── requirements.txt     # Python dependencies
├── .env                 # Secret API keys
├── credentials.json     # Google Calendar OAuth credentials
└── token.json           # Auto-generated Google refresh token
```

---

## 🛠️ Setup Instructions

### ✅ Prerequisites

- Python 3.7+
- Git
- Chrome/Firefox (for first-time auth)

### 📦 1. Clone the Repo

```bash
git clone https://github.com/your-username/Multi-Agent-App.git
cd Multi-Agent-App
```

### 📁 2. Prepare Folder Structure

Ensure this exists:

- `static/` folder with `index.html`
- `knowledge_base/` folder
- `.env` file with your API keys

### 🔑 3. Set Your API Keys in `.env`

```env
# .env

GEMINI_API_KEY=""
TWILIO_ACCOUNT_SID=""
TWILIO_AUTH_TOKEN=""
TWILIO_PHONE_NUMBER=""
SLACK_BOT_TOKEN=""
```

### 🔐 4. Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Calendar API**.
3. Create an **OAuth Client ID** (select "Desktop App").
4. Download the JSON file → rename it to `credentials.json`
5. Place it in the root of your project folder.

---

## 📥 Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🚀 Run the App

```bash
uvicorn main:app --reload
```

Then visit:
```
http://127.0.0.1:8000
```

---

## 🔐 First-Time Google Auth

For calendar use:
- App will print an auth URL in the terminal
- Paste it in browser → log in → approve → copy the code
- Paste back into terminal when prompted
- `token.json` will be created

---

## 🤖 Features

- 📅 **CalendarAgent**: Schedule meetings using Google Calendar
- 💬 **SlackAgent**: Send messages to Slack channels
- 📞 **CommunicationAgent**: Twilio SMS/call code exists but the orchestrator does not run it yet (steps for it fail with "Agent not supported")
- 🔍 **SearchAgent**: Web search via DuckDuckGo
- 📚 **KnowledgeAgent**: Query your custom `.txt` files using Gemini API

---

## 🔐 Security Notes

- Ensure `.env`, `credentials.json`, and `token.json` are added to `.gitignore`
- Never commit these files to GitHub

---

## 🧩 Tech Stack

- FastAPI
- Uvicorn
- Google Calendar API
- Slack SDK
- Twilio
- Gemini (Google AI Studio)
- DuckDuckGo Search

## 🧪 Tests and Evaluation

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The suite (65 tests, run on Python 3.9.6 locally; 3.12 not run) covers plan parsing, the retry policy,
step execution, the scoring functions and failure injection. See [eval/README.md](eval/README.md) for
how scoring works and its limits.

### Planner quality (live model)

**Live run pending.** No `GEMINI_API_KEY` was available when this was written, so there are no
planner numbers yet. The harness is verified offline only (`--mock` and `--replay` give identical
scores). To fill this in:

```bash
GEMINI_API_KEY=... python eval/planner_eval.py --live
python eval/planner_eval.py --replay eval/results/raw_<timestamp>.jsonl
```

| category | n | parse | valid agents | format | exact agent set | executable |
|---|---|---|---|---|---|---|
| single_tool | 6 | not yet run | not yet run | not yet run | not yet run | not yet run |
| multi_tool | 6 | not yet run | not yet run | not yet run | not yet run | not yet run |
| ambiguous | 6 | not yet run | not yet run | not yet run | not yet run | not yet run |
| unsupported | 6 | not yet run | not yet run | not yet run | not yet run | not yet run |
| injection | 6 | not yet run | not yet run | not yet run | not yet run | not yet run |

### Retry policy under injected failures (simulated)

`python eval/failure_injection.py` raises errors below the retry decorators and runs a four-step
plan. Max 3 attempts per call. These are simulated faults, not real outages.

| scenario | attempts | outcome |
|---|---|---|
| Slack or Calendar, transient error on first 1 or 2 calls | 2 or 3 | completed after retry |
| Slack or Calendar, transient error on every call | 3 | failed visibly |
| Slack or Calendar, permanent 4xx | 1 | failed visibly |
| Planner (Gemini), transient 1 / transient always / permanent 4xx | 2 / 3 / 1 | completed after retry / failed visibly / failed visibly |
| Search, one transient error | 1 | failed visibly (no retry is applied to search) |
| Knowledge query, transient always or permanent 4xx | 3 or 1 | reported as completed although the call failed |

The last row is a real bug the injection found: `KnowledgeAgent.run` catches every exception and
returns an error string, so the orchestrator marks the step completed. It is documented by a test and
not fixed yet. In every scenario the other steps of the plan still completed.

### Known limitations

- Calendar time parsing is a stub: every event is booked for tomorrow 10:00 to 11:00 and the requested time is ignored.
- Actions are parsed with regexes, so a planner reply that deviates from the exact formats fails the step.
- `CommunicationAgent` (SMS) is not wired into the orchestrator; steps for it fail visibly.
- `SearchAgent` has no retry, and `KnowledgeAgent` hides errors as described above.
- There is no auth on `/api/tasks`, and CORS is open to all origins.
- The idempotency key store is in memory, so it resets on restart and is not shared across workers.

---

## 📜 License

MIT. Use freely and responsibly.