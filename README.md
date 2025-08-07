# 🧠 Multi-Agent Task Automation System

An intelligent task automation assistant powered by multiple agents and AI services. This app enables you to create calendar events, send Slack messages, perform web searches, consult a local knowledge base, and interact via Twilio — all using natural language commands.

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

- 📅 **CalendarAgent** – Schedule meetings using Google Calendar
- 💬 **SlackAgent** – Send messages to Slack channels
- 📞 **CommunicationAgent** – SMS and phone calls using Twilio
- 🔍 **SearchAgent** – Web search via DuckDuckGo
- 📚 **KnowledgeAgent** – Query your custom `.txt` files using Gemini API

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

---

## 📜 License

MIT — Use freely and responsibly.