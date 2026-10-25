import pytest

from eval.metrics import aggregate, normalize_plan, score_case

SLACK = {"agent": "SlackAgent", "action": 'Post "hi" to #general'}
SEARCH = {"agent": "SearchAgent", "action": "Search for fastapi"}


def case(expected, cat="single_tool"):
    return {"id": "c", "category": cat, "expected_agents": expected}


def test_valid_plan_scores_perfectly():
    r = score_case(case(["SlackAgent"]), [SLACK], True)
    assert r["schema_ok"] and r["agents_valid"] and r["format_ok"] and r["executable"]
    assert r["agent_precision"] == 1.0 and r["agent_recall"] == 1.0
    assert r["exact_agent_set"] and r["exact_sequence"]


def test_wrong_agent_name():
    plan = [{"agent": "ShellAgent", "action": "rm -rf /"}]
    r = score_case(case(["SlackAgent"]), plan, True)
    assert r["schema_ok"] and not r["agents_valid"] and not r["format_ok"]
    assert not r["executable"]
    assert r["agent_precision"] == 0.0 and r["agent_recall"] == 0.0


def test_bad_action_format():
    plan = [{"agent": "SlackAgent", "action": "Tell #general hi"}]
    r = score_case(case(["SlackAgent"]), plan, True)
    assert r["agents_valid"] and not r["format_ok"]
    assert r["exact_agent_set"]  # right agent, wrong format: the two are scored separately


def test_missing_field():
    r = score_case(case(["SlackAgent"]), [{"agent": "SlackAgent"}], True)
    assert not r["schema_ok"] and not r["agents_valid"] and not r["exact_agent_set"]
    assert r["agent_precision"] == 0.0


def test_extra_step_lowers_precision_not_recall():
    r = score_case(case(["SlackAgent"]), [SLACK, SEARCH], True)
    assert r["agent_precision"] == 0.5 and r["agent_recall"] == 1.0
    assert not r["exact_agent_set"]


def test_order_matters_only_for_exact_sequence():
    c = case(["SearchAgent", "SlackAgent"], "multi_tool")
    assert score_case(c, [SEARCH, SLACK], True)["exact_sequence"]
    swapped = score_case(c, [SLACK, SEARCH], True)
    assert swapped["exact_agent_set"] and not swapped["exact_sequence"]


def test_unsupported_empty_plan_is_correct():
    r = score_case(case([], "unsupported"), [], True)
    assert r["exact_agent_set"] and r["agent_precision"] == 1.0 and r["agent_recall"] == 1.0


def test_unsupported_invented_agent_is_wrong():
    plan = [{"agent": "EmailAgent", "action": "Send email"}]
    r = score_case(case([], "unsupported"), plan, True)
    assert not r["agents_valid"] and not r["exact_agent_set"] and r["agent_precision"] == 0.0


def test_empty_plan_when_something_expected():
    r = score_case(case(["SlackAgent"]), [], True)
    assert r["agent_precision"] == 0.0 and r["agent_recall"] == 0.0


def test_communication_agent_is_valid_but_not_executable():
    plan = [{"agent": "CommunicationAgent", "action": "Send SMS to +1555: hi"}]
    r = score_case(case(["CommunicationAgent"]), plan, True)
    assert r["agents_valid"] and r["format_ok"] and not r["executable"]


def test_parse_failure_scores_zero():
    r = score_case(case([]), None, False)
    assert not any([r["parse_ok"], r["schema_ok"], r["exact_agent_set"], r["executable"]])
    assert r["agent_precision"] == 0.0 and r["agent_recall"] == 0.0


@pytest.mark.parametrize("action", [
    "Add knowledge: 'x' in notes", "What is the refund policy?",
])
def test_knowledge_formats(action):
    plan = [{"agent": "KnowledgeAgent", "action": action}]
    assert score_case(case(["KnowledgeAgent"]), plan, True)["format_ok"]


def test_normalize_single_object():
    assert normalize_plan(SLACK) == [SLACK]
    assert normalize_plan([SLACK]) == [SLACK]


def test_aggregate_reports_n_per_category():
    rows = [
        score_case(case(["SlackAgent"], "a"), [SLACK], True),
        score_case(case(["SlackAgent"], "a"), [], True),
        score_case(case([], "b"), [], True),
    ]
    agg = aggregate(rows)
    assert agg["overall"]["n"] == 3
    assert agg["by_category"]["a"]["n"] == 2
    assert agg["by_category"]["a"]["exact_agent_set"] == 0.5
    assert agg["by_category"]["b"]["n"] == 1
