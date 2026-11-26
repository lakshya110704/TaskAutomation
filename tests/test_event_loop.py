"""Slow outbound calls must not freeze the server.

The HTTP clients are blocking, so each agent runs them in a worker thread.
These tests make the call sleep and check that another coroutine (standing in
for websocket updates and other requests) keeps running meanwhile.
"""
import asyncio
import json
import time

import pytest

import agents
import orchestrator
from orchestrator import TaskOrchestrator

SLOW = 0.5


class FakeResponse:
    def __init__(self, text):
        self._text = text

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


async def ticks_during(coro):
    """Run coro and count how often a 50 ms ticker gets to run meanwhile."""
    ticks = 0
    done = False

    async def ticker():
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done = True
        await task
    return result, ticks


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(orchestrator, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(agents, "GEMINI_API_KEY", "test")


async def test_planner_call_does_not_block_the_loop():
    orch = object.__new__(TaskOrchestrator)

    def slow_post(payload):
        time.sleep(SLOW)
        return FakeResponse(json.dumps([{"agent": "SlackAgent", "action": "x"}]))

    orch._post_to_gemini = slow_post
    plan, ticks = await ticks_during(orch._gemini_request({"user_prompt": "x"}, "{user_prompt}"))
    assert plan == [{"agent": "SlackAgent", "action": "x"}]
    assert ticks >= 5


async def test_knowledge_call_does_not_block_the_loop():
    agent = object.__new__(agents.KnowledgeAgent)
    agent.knowledge = "Our CEO is Priya."

    def slow_post(url, headers, payload):
        time.sleep(SLOW)
        return FakeResponse("Priya")

    agent._post = slow_post
    answer, ticks = await ticks_during(agent.run("Who is the CEO?"))
    assert answer == "Priya"
    assert ticks >= 5


async def test_search_call_does_not_block_the_loop():
    agent = agents.SearchAgent()

    def slow_fetch(query):
        time.sleep(SLOW)
        return [{"title": "T", "body": "B"}]

    agent._fetch = slow_fetch
    result, ticks = await ticks_during(agent.run("q"))
    assert result == "T: B"
    assert ticks >= 5


async def test_calendar_call_does_not_block_the_loop():
    agent = object.__new__(agents.CalendarAgent)

    def slow_insert(details):
        time.sleep(SLOW)
        return {"htmlLink": "https://calendar/event"}

    agent._insert_event = slow_insert
    link, ticks = await ticks_during(agent.run({}))
    assert link == "https://calendar/event"
    assert ticks >= 5
