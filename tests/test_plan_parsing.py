import json

import pytest

import orchestrator
from orchestrator import TaskOrchestrator

PLAN = [{"agent": "SlackAgent", "action": 'Post "hi" to #general'}]
PLAN_JSON = json.dumps(PLAN)


class FakeResponse:
    def __init__(self, text):
        self._text = text

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


class FakeWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(json.loads(message))


def make_orchestrator(model_text="[]", prompt="x"):
    """Build an orchestrator without the real __init__ (needs Slack/Google creds)."""
    orch = object.__new__(TaskOrchestrator)
    orch.task_id = "t"
    orch.prompt = prompt
    orch.ws_manager = FakeWS()
    orch.plan = []
    orch.context = {}
    orch.gemini_calls = 0

    def fake_post(payload):
        orch.gemini_calls += 1
        return FakeResponse(model_text)

    orch._post_to_gemini = fake_post
    return orch


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(orchestrator, "GEMINI_API_KEY", "test")


async def parse(text):
    orch = make_orchestrator(text)
    return await orch._gemini_request({"user_prompt": "x"}, "{user_prompt}")


async def test_plain_json_array():
    assert await parse(PLAN_JSON) == PLAN


async def test_json_fence_with_language():
    assert await parse(f"```json\n{PLAN_JSON}\n```") == PLAN


async def test_json_fence_uppercase_language():
    assert await parse(f"```JSON\n{PLAN_JSON}\n```") == PLAN


async def test_fence_without_language():
    assert await parse(f"```\n{PLAN_JSON}\n```") == PLAN


async def test_fence_with_trailing_whitespace_and_newline():
    assert await parse(f"```json\n{PLAN_JSON}\n```  \n\n") == PLAN


async def test_single_object_is_returned_as_is_and_wrapped_by_execute_plan():
    obj = PLAN[0]
    assert await parse(json.dumps(obj)) == obj
    # execute_plan normalises a single object into a one-step list
    orch = make_orchestrator(json.dumps(obj))

    async def noop(step):
        pass

    orch._execute_step = noop
    await orch.execute_plan()
    assert orch.plan == [obj]


async def test_prose_before_json_is_rejected_clearly():
    # Documented behaviour: we do not try to dig JSON out of prose. The model is
    # told to reply with JSON only, so prose means a bad plan and the task aborts
    # with a "Plan error" log rather than guessing.
    with pytest.raises(json.JSONDecodeError):
        await parse(f"Here is the plan:\n{PLAN_JSON}")


async def test_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        await parse("```json\n[{not json}]\n```")


async def test_slack_shortcut_regex_skips_the_llm():
    orch = make_orchestrator(
        prompt="Post a message on #general channel in Slack saying 'hello'"
    )

    async def noop(step):
        pass

    orch._execute_step = noop
    await orch.execute_plan()
    assert orch.plan == [
        {"agent": "SlackAgent", "action": 'Post "hello" to #general'}
    ]
    assert orch.gemini_calls == 0
