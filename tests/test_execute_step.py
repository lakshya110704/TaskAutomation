import json

import pytest

from orchestrator import EXECUTABLE_AGENTS, PLANNER_AGENTS, TaskOrchestrator


class FakeWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(json.loads(message))

    @property
    def final_status(self):
        return [m for m in self.messages if m["type"] == "status_update"][-1]["status"]

    @property
    def final_log(self):
        return [m for m in self.messages if m["type"] == "log"][-1]["message"]


class Recorder:
    """Fake agent: records the calls it gets, never touches the network."""

    def __init__(self, result="ok"):
        self.calls = []
        self.result = result

    async def run(self, arg):
        self.calls.append(arg)
        return self.result

    async def execute(self, arg):
        self.calls.append(arg)
        return self.result

    async def add_knowledge(self, filename, content):
        self.calls.append((filename, content))
        return "stored"


def make_orchestrator(**agents):
    orch = object.__new__(TaskOrchestrator)
    orch.ws_manager = FakeWS()
    orch.knowledge_agent = agents.get("knowledge", Recorder())
    orch.search_agent = agents.get("search", Recorder("Title: body\nSecond: line"))
    orch.slack_agent = agents.get("slack", Recorder())
    orch.calendar_agent = agents.get("calendar", Recorder("http://cal/link"))
    return orch


STEPS = {
    "KnowledgeAgent": "What is the refund policy?",
    "SearchAgent": "Search for python asyncio",
    "SlackAgent": 'Post "hi" to #general',
    "CalendarAgent": "Schedule team sync for tomorrow",
}


@pytest.mark.parametrize("agent", EXECUTABLE_AGENTS)
async def test_executable_agents_run_their_real_method(agent):
    orch = make_orchestrator()
    await orch._execute_step({"agent": agent, "action": STEPS[agent]})
    assert orch.ws_manager.final_status == "completed"
    attr = {"KnowledgeAgent": "knowledge_agent", "SearchAgent": "search_agent",
            "SlackAgent": "slack_agent", "CalendarAgent": "calendar_agent"}[agent]
    assert len(getattr(orch, attr).calls) == 1


async def test_search_reports_a_short_result():
    orch = make_orchestrator()
    await orch._execute_step({"agent": "SearchAgent", "action": STEPS["SearchAgent"]})
    assert orch.ws_manager.final_log == "Search completed: Title: body"


@pytest.mark.parametrize("result", ["No results found.", "Error during search: boom"])
async def test_search_failure_is_reported_as_failed(result):
    orch = make_orchestrator(search=Recorder(result))
    await orch._execute_step({"agent": "SearchAgent", "action": STEPS["SearchAgent"]})
    assert orch.ws_manager.final_status == "failed"


@pytest.mark.parametrize("agent", ["CommunicationAgent", "TeleportAgent", ""])
async def test_unsupported_agents_fail_loudly(agent):
    orch = make_orchestrator()
    await orch._execute_step({"agent": agent, "action": "Send SMS to +1555: hi"})
    assert orch.ws_manager.final_status == "failed"
    assert "not supported" in orch.ws_manager.final_log
    assert not any(m.get("message", "").startswith("Executed") for m in orch.ws_manager.messages)


async def test_no_planner_agent_can_report_executed_without_work():
    for agent in PLANNER_AGENTS:
        orch = make_orchestrator()
        await orch._execute_step({"agent": agent, "action": STEPS.get(agent, "x")})
        status = orch.ws_manager.final_status
        if agent in EXECUTABLE_AGENTS:
            assert status == "completed"
        else:
            assert status == "failed"


async def test_knowledge_answer_is_shown_and_passed_to_slack():
    orch = make_orchestrator(knowledge=Recorder("The CEO is\nPriya Sharma."))
    await orch._execute_step({"agent": "KnowledgeAgent", "action": "What is the CEO?"})
    assert orch.ws_manager.final_log == "Answer: The CEO is\nPriya Sharma."
    for placeholder in ["{result}", "The CEO is [CEO name]"]:
        await orch._execute_step({"agent": "SlackAgent", "action": f'Post "{placeholder}" to #demo'})
        assert orch.slack_agent.calls[-1] == 'Post "The CEO is Priya Sharma." to #demo'


async def test_slack_message_without_placeholder_is_unchanged():
    orch = make_orchestrator()
    orch.last_answer = "something"
    await orch._execute_step({"agent": "SlackAgent", "action": 'Post "Team meeting at 3pm" to #demo'})
    assert orch.slack_agent.calls[-1] == 'Post "Team meeting at 3pm" to #demo'


@pytest.mark.parametrize("action,days,hour,minute", [
    ("Schedule team meeting for tomorrow at 3pm", 1, 15, 0),
    ("Schedule standup for today at 9:30 am", 0, 9, 30),
    ("Schedule lunch for tomorrow at 12pm", 1, 12, 0),
    ("Schedule review for tomorrow", 1, 10, 0),
])
def test_calendar_time_parsing(action, days, hour, minute):
    from datetime import datetime, timedelta
    d = make_orchestrator()._parse_calendar_action(action)
    start = datetime.fromisoformat(d["start_time"])
    assert start.date() == (datetime.now() + timedelta(days=days)).date()
    assert (start.hour, start.minute) == (hour, minute)
    assert datetime.fromisoformat(d["end_time"]) - start == timedelta(hours=1)
