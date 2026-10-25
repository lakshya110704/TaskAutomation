import pytest

from eval.failure_injection import run_all

@pytest.fixture(scope="module")
def rows():
    return {r["scenario"]: r for r in run_all()}


@pytest.mark.parametrize("target", ["slack", "calendar"])
def test_transient_below_limit_is_retried_to_success(rows, target):
    for n, attempts in ((1, 2), (2, 3)):
        r = rows[f"{target} transient N={n}"]
        assert r["outcome"] == "completed after retry" and r["attempts"] == attempts


@pytest.mark.parametrize("target", ["slack", "calendar"])
def test_exhausted_and_permanent_fail_visibly(rows, target):
    assert rows[f"{target} transient N=3"]["attempts"] == 3
    assert rows[f"{target} transient N=3"]["outcome"] == "failed visibly"
    assert rows[f"{target} permanent"]["attempts"] == 1
    assert rows[f"{target} permanent"]["outcome"] == "failed visibly"


def test_one_failing_agent_does_not_break_other_steps(rows):
    assert all(r["other_steps_ok"] in (True, None) for r in rows.values())


def test_planner_call_follows_the_same_policy(rows):
    assert rows["planner transient N=1"]["outcome"] == "completed after retry"
    assert rows["planner transient N=3"]["attempts"] == 3
    assert rows["planner permanent"]["attempts"] == 1


def test_search_has_no_retry(rows):
    r = rows["search transient N=1"]
    assert r["attempts"] == 1 and r["outcome"] == "failed visibly"


def test_knowledge_agent_swallows_errors_known_issue(rows):
    # KnowledgeAgent.run catches every exception and returns an error string, so the
    # orchestrator reports the step as completed. Documented in the README; if this
    # test starts failing, the bug was fixed and the expectation should flip.
    assert rows["knowledge transient N=3"]["outcome"].startswith("FALSE SUCCESS")
    assert rows["knowledge permanent"]["outcome"].startswith("FALSE SUCCESS")
