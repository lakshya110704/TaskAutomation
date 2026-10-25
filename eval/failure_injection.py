"""End-to-end check of the retry policy.

Faults are injected BELOW the retry decorators (at the SDK or requests level), then a
multi-step plan runs through TaskOrchestrator._execute_step. For each scenario the
report says whether the targeted step completed, was retried, or failed visibly.

  python eval/failure_injection.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httplib2  # noqa: E402
import requests  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402
from slack_sdk.errors import SlackApiError  # noqa: E402
from tenacity import wait_none  # noqa: E402

import agents  # noqa: E402
import orchestrator  # noqa: E402

RESULTS = os.path.join(ROOT, "eval", "results")

PLAN = [
    {"agent": "SlackAgent", "action": 'Post "hi" to #general'},
    {"agent": "CalendarAgent", "action": "Schedule team sync for tomorrow"},
    {"agent": "KnowledgeAgent", "action": "What is the refund policy?"},
    {"agent": "SearchAgent", "action": "Search for python asyncio"},
]
TARGET_STEP = {"slack": 0, "calendar": 1, "knowledge": 2, "search": 3}


def zero_retry_waits():
    """Keep the real retry policy (attempts, which errors) but skip the sleeping."""
    for fn in (agents.SlackAgent._post, agents.KnowledgeAgent._post,
               agents.CalendarAgent._insert_event, agents.CommunicationAgent.send_sms,
               agents.CommunicationAgent.make_call, orchestrator.TaskOrchestrator._post_to_gemini):
        fn.retry.wait = wait_none()


class Fault:
    """Fails the first n calls (transient) or every call (permanent); counts attempts."""

    def __init__(self, kind=None, n=0):
        self.kind, self.n = kind, n
        self.attempts = 0
        self.succeeded = False

    def should_fail(self):
        self.attempts += 1
        failing = self.kind == "permanent" or (self.kind == "transient" and self.attempts <= self.n)
        if not failing:
            self.succeeded = True
        return failing


def _http_response(status):
    resp = requests.Response()
    resp.status_code = status
    return resp


class FakeWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(json.loads(message))

    def last_status(self):
        return [m for m in self.messages if m["type"] == "status_update"][-1]["status"]

    def last_log(self):
        return [m for m in self.messages if m["type"] == "log"][-1]["message"]


# One (transient_error, permanent_error) factory per target, matching the real SDK errors.
ERRORS = {
    "slack": (lambda: SlackApiError("x", SimpleNamespace(status_code=503)),
              lambda: SlackApiError("x", SimpleNamespace(status_code=400))),
    "calendar": (lambda: HttpError(httplib2.Response({"status": 503}), b"{}"),
                 lambda: HttpError(httplib2.Response({"status": 404}), b"{}")),
    "knowledge": (lambda: requests.ConnectionError("connection reset"),
                  lambda: requests.HTTPError("400", response=_http_response(400))),
    "search": (lambda: RuntimeError("search backend timeout"),
               lambda: RuntimeError("search backend timeout")),
}


def _raise(target, fault):
    transient, permanent = ERRORS[target]
    raise (permanent() if fault.kind == "permanent" else transient())


def _build_orchestrator(faults):
    orch = object.__new__(orchestrator.TaskOrchestrator)
    orch.ws_manager = FakeWS()
    orch.slack_agent = agents.SlackAgent(token="test")
    orch.knowledge_agent = object.__new__(agents.KnowledgeAgent)
    orch.knowledge_agent.knowledge = "context"
    orch.search_agent = agents.SearchAgent()
    orch.calendar_agent = object.__new__(agents.CalendarAgent)
    orch.calendar_agent.creds = "test"

    async def fake_post_message(channel, text):
        if faults["slack"].should_fail():
            _raise("slack", faults["slack"])
        return {"ok": True}

    orch.slack_agent.client.chat_postMessage = fake_post_message
    return orch


def _patches(faults):
    def fake_requests_post(url, **kwargs):
        fault = faults["knowledge"]
        if fault.should_fail():
            _raise("knowledge", fault)
        resp = _http_response(200)
        resp.json = lambda: {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]}
        return resp

    class FakeService:
        def events(self):
            return self

        def insert(self, calendarId, body):
            return self

        def execute(self):
            if faults["calendar"].should_fail():
                _raise("calendar", faults["calendar"])
            return {"htmlLink": "http://calendar/event"}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, max_results=3):
            if faults["search"].should_fail():
                _raise("search", faults["search"])
            return [{"title": "T", "body": "B"}]

    return [
        mock.patch.object(requests, "post", fake_requests_post),
        mock.patch.object(agents, "build", lambda *a, **k: FakeService()),
        mock.patch.object(agents, "DDGS", FakeDDGS),
    ]


def _classify(status, fault):
    if status == "failed":
        return "failed visibly"
    if not fault.succeeded:
        return "FALSE SUCCESS (reported completed, call never succeeded)"
    return "completed after retry" if fault.attempts > 1 else "completed first try"


def run_step_scenario(target, kind, n):
    zero_retry_waits()
    faults = {t: Fault() for t in TARGET_STEP}
    faults[target] = Fault(kind, n)
    orch = _build_orchestrator(faults)
    statuses = []
    patches = _patches(faults)
    for p in patches:
        p.start()
    try:
        for step in PLAN:
            asyncio.run(orch._execute_step(step))
            statuses.append(orch.ws_manager.last_status())
    finally:
        for p in patches:
            p.stop()
    idx = TARGET_STEP[target]
    others_ok = all(s == "completed" for i, s in enumerate(statuses) if i != idx)
    return {
        "scenario": f"{target} {kind}" + (f" N={n}" if kind == "transient" else ""),
        "target": target, "kind": kind, "n": n,
        "attempts": faults[target].attempts,
        "outcome": _classify(statuses[idx], faults[target]),
        "other_steps_ok": others_ok,
    }


def run_planner_scenario(kind, n):
    zero_retry_waits()
    fault = Fault(kind, n)

    def fake_post(url, **kwargs):
        if fault.should_fail():
            _raise("knowledge", fault)
        resp = _http_response(200)
        resp.json = lambda: {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}
        return resp

    orch = object.__new__(orchestrator.TaskOrchestrator)
    old_key = orchestrator.GEMINI_API_KEY
    orchestrator.GEMINI_API_KEY = "test"
    try:
        with mock.patch.object(requests, "post", fake_post):
            try:
                asyncio.run(orch._gemini_request({"user_prompt": "x"}, "{user_prompt}"))
                outcome = "completed after retry" if fault.attempts > 1 else "completed first try"
            except Exception:
                outcome = "failed visibly"
    finally:
        orchestrator.GEMINI_API_KEY = old_key
    return {"scenario": f"planner {kind}" + (f" N={n}" if kind == "transient" else ""),
            "target": "planner", "kind": kind, "n": n, "attempts": fault.attempts,
            "outcome": outcome, "other_steps_ok": None}


def run_all():
    rows = []
    for target in ("slack", "calendar", "knowledge"):
        for kind, n in (("transient", 1), ("transient", 2), ("transient", 3), ("permanent", 0)):
            rows.append(run_step_scenario(target, kind, n))
    rows.append(run_step_scenario("search", "transient", 1))
    for kind, n in (("transient", 1), ("transient", 3), ("permanent", 0)):
        rows.append(run_planner_scenario(kind, n))
    return rows


def to_markdown(rows):
    lines = ["# Failure injection", "",
             "Faults are raised below the retry decorators; the retry policy is the real one "
             "(3 attempts, waits skipped). Plan: Slack, Calendar, Knowledge, Search.", "",
             "| scenario | attempts | outcome | other steps ok |", "|---|---|---|---|"]
    for r in rows:
        other = "-" if r["other_steps_ok"] is None else ("yes" if r["other_steps_ok"] else "NO")
        lines.append(f"| {r['scenario']} | {r['attempts']} | {r['outcome']} | {other} |")
    return "\n".join(lines) + "\n"


def main():
    rows = run_all()
    md = to_markdown(rows)
    print(md)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"failure_injection_{ts}.md"), "w") as f:
        f.write(md)
    with open(os.path.join(RESULTS, f"failure_injection_{ts}.json"), "w") as f:
        json.dump(rows, f, indent=2)


if __name__ == "__main__":
    main()
