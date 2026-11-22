### orchestrator.py

import os
import re
import json
import asyncio
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from agents import SlackAgent, KnowledgeAgent, SearchAgent, CalendarAgent, CommunicationAgent
from retry import with_retry

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# The key goes in a header, not the URL, so HTTP errors (shown in the UI log) never contain it.
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite:generateContent"
)

PLANNER_PROMPT_TEMPLATE = """
You are an expert planning agent. Your job is to create a plan to fulfill a user's request.
Here are the available agents and their EXACT action formats:

- "KnowledgeAgent":
  * To add knowledge: "Add knowledge: 'content here' in filename"
  * To query: "What is [question]?"
- "SearchAgent": "Search for [query]"
- "SlackAgent": "Post \"message text\" to #channel"
- "CalendarAgent": "Schedule [event name] for [time]"
- "CommunicationAgent": "Send SMS to [number]: [message]"

CRITICAL: Use the exact formats shown above. For SlackAgent, always use: Post "message"
to #channel
If a Slack message must contain the answer from an earlier KnowledgeAgent step, write the
message as exactly {{result}}, for example: Post "{{result}}" to #channel
For CalendarAgent, keep the day and time the user gave, for example: Schedule team sync for tomorrow at 3pm

Respond with ONLY a JSON array of steps (no backticks or extra text).
Each step must have "agent" and "action" fields.

User Request: "{user_prompt}"
"""

# Every agent name the planner prompt may use, and the subset with a real executor
# in TaskOrchestrator._execute_step. Keep both in sync with that method.
PLANNER_AGENTS = ("KnowledgeAgent", "SearchAgent", "SlackAgent", "CalendarAgent", "CommunicationAgent")
EXECUTABLE_AGENTS = ("KnowledgeAgent", "SearchAgent", "SlackAgent", "CalendarAgent")


class TaskOrchestrator:
    def __init__(self, task_id: str, prompt: str, ws_manager):
        self.task_id = task_id
        self.prompt = prompt
        self.ws_manager = ws_manager

        self.knowledge_agent = KnowledgeAgent()
        self.search_agent = SearchAgent()
        self.calendar_agent = CalendarAgent()
        self.communication_agent = CommunicationAgent()

        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            raise RuntimeError("Missing SLACK_BOT_TOKEN")
        self.slack_agent = SlackAgent(token=slack_token)

        self.plan = []
        self.context = {}

    @with_retry()
    def _post_to_gemini(self, payload: dict):
        r = requests.post(GEMINI_API_URL, json=payload, timeout=60,
                          headers={"x-goog-api-key": GEMINI_API_KEY})
        r.raise_for_status()
        return r

    async def _gemini_request(self, data: dict, template: str, is_json=True):
        if not GEMINI_API_KEY:
            raise RuntimeError("Missing GEMINI_API_KEY")
        payload = {"contents": [{"parts": [{"text": template.format(**data)}]}]}
        r = self._post_to_gemini(payload)
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if is_json:
            clean = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
            clean = re.sub(r"\s*```$", "", clean).strip()
            return json.loads(clean)
        return text

    async def execute_plan(self):
        m = re.search(
            r"Post a message on\s+(#[^\s]+)\s+channel in Slack saying ['\"](.+?)['\"]",
            self.prompt,
            flags=re.IGNORECASE
        )
        if m:
            channel, msg = m.group(1), m.group(2)
            action = f'Post "{msg}" to {channel}'
            self.plan = [{"agent": "SlackAgent", "action": action}]
        else:
            await self.ws_manager.broadcast(json.dumps({
                "type": "log",
                "agent": "PlannerAgent",
                "message": "Generating plan...",
                "log_type": "info"
            }))
            try:
                plan = await self._gemini_request({"user_prompt": self.prompt}, PLANNER_PROMPT_TEMPLATE)
                self.plan = plan if isinstance(plan, list) else [plan]
            except Exception as e:
                await self.ws_manager.broadcast(json.dumps({
                    "type": "log",
                    "agent": "System",
                    "message": f"Plan error: {e}",
                    "log_type": "error"
                }))
                return
        await self.ws_manager.broadcast(json.dumps({"type": "plan", "steps": self.plan}))
        for step in self.plan:
            await asyncio.sleep(1)
            await self._execute_step(step)
        await self.ws_manager.broadcast(json.dumps({
            "type": "log",
            "agent": "System",
            "message": "Task completed",
            "log_type": "success"
        }))

    async def _execute_step(self, step):
        agent, action = step["agent"], step["action"]
        await self.ws_manager.broadcast(json.dumps({
            "type": "status_update", "step_action": action, "status": "in-progress"
        }))
        await self.ws_manager.broadcast(json.dumps({
            "type": "log", "agent": agent, "message": f"Starting: {action}", "log_type": "info"
        }))

        try:
            if agent == "KnowledgeAgent":
                if action.lower().startswith("add knowledge"):
                    match = re.search(r"add knowledge:\s*['\"](.+?)['\"].*in\s+(\w+)", action, re.IGNORECASE)
                    if match:
                        content, filename = match.groups()
                        resp = await self.knowledge_agent.add_knowledge(filename, content)
                        msg = resp
                    else:
                        raise ValueError(f"Could not parse knowledge add action: {action}")
                else:
                    resp = await self.knowledge_agent.run(action)
                    self.last_answer = resp
                    msg = f"Answer: {resp}"

            elif agent == "SlackAgent":
                resp = await self.slack_agent.execute(self._fill_result(action))
                msg = f"Slack message posted successfully"

            elif agent == "CalendarAgent":
                event_details = self._parse_calendar_action(action)
                resp = await self.calendar_agent.run(event_details)
                msg = f"Calendar event created: {resp}"

            elif agent == "SearchAgent":
                resp = await self.search_agent.run(action)
                if resp.startswith("Error during search") or resp == "No results found.":
                    raise RuntimeError(resp)
                first = resp.splitlines()[0]
                msg = f"Search completed: {first[:120]}"

            elif agent == "CommunicationAgent":
                # The SMS action is not parsed or sent yet; fail visibly instead of
                # reporting success for work that never happened.
                raise NotImplementedError("Agent not supported: CommunicationAgent")

            else:
                raise NotImplementedError(f"Agent not supported: {agent}")

            status = "completed"
            lt = "success"

        except Exception as e:
            msg = f"Error: {e}"
            status = "failed"
            lt = "error"

        await self.ws_manager.broadcast(json.dumps({
            "type": "status_update", "step_action": action, "status": status
        }))
        await self.ws_manager.broadcast(json.dumps({
            "type": "log", "agent": agent, "message": msg, "log_type": lt
        }))

    def _fill_result(self, action):
        """Put the last knowledge answer into a Slack message that asks for it with
        {result} or a [placeholder]. The whole message becomes the answer."""
        answer = getattr(self, "last_answer", None)
        m = re.match(r'^(Post\s+")(.+)("\s+to\s+#\S+)$', action, flags=re.IGNORECASE)
        if not answer or not m or not re.search(r"\{result\}|\[[^\]]+\]", m.group(2)):
            return action
        return m.group(1) + " ".join(answer.split()) + m.group(3)

    def _parse_calendar_action(self, action):
        title_match = re.search(r'schedule\s+(?:a\s+)?(.+?)\s+for', action, re.IGNORECASE)
        title = title_match.group(1) if title_match else "Meeting"
        # shortcut: only "today"/"tomorrow" and times like 3pm or 3:30 pm; anything else falls back to tomorrow 10:00.
        day = datetime.now() + timedelta(days=0 if re.search(r"\btoday\b", action, re.IGNORECASE) else 1)
        t = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", action, re.IGNORECASE)
        hour, minute = 10, 0
        if t and 1 <= int(t.group(1)) <= 12:
            hour = int(t.group(1)) % 12 + (12 if t.group(3).lower() == "p" else 0)
            minute = int(t.group(2) or 0)
        start_time = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end_time = start_time + timedelta(hours=1)
        return {
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        }