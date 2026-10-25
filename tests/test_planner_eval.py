import json

import pytest

import orchestrator
from eval import planner_eval
from eval.metrics import aggregate


def test_dataset_is_balanced_and_uses_real_agents():
    cases = planner_eval.load_dataset()
    assert len(cases) == 30
    cats = {}
    for c in cases:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
        assert set(c["expected_agents"]) <= set(orchestrator.PLANNER_AGENTS)
    assert set(cats) == {"single_tool", "multi_tool", "ambiguous", "unsupported", "injection"}
    assert max(cats.values()) - min(cats.values()) <= 1
    assert len({c["id"] for c in cases}) == len(cases)


def test_mock_scores_are_deterministic_and_replay_matches(tmp_path):
    cases = planner_eval.load_dataset()
    records = planner_eval.mock_records(cases)
    path = tmp_path / "raw.jsonl"
    planner_eval.write_jsonl(path, records)
    first, _ = planner_eval.score_records(cases, records)
    replayed, _ = planner_eval.score_records(cases, planner_eval.load_jsonl(path))
    assert aggregate(first) == aggregate(replayed)
    # scripted modes: clean + fenced parse, prose + truncated JSON do not
    assert aggregate(first)["overall"]["parse_ok"] == pytest.approx(20 / 30)


def test_api_error_record_counts_as_failure_not_crash():
    cases = planner_eval.load_dataset()[:1]
    rec = [{"id": cases[0]["id"], "raw_text": None, "api_error": "HTTPError: 429"}]
    rows, api_errors = planner_eval.score_records(cases, rec)
    assert api_errors == 1 and rows[0]["parse_ok"] is False


def test_live_mode_refuses_without_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(orchestrator, "GEMINI_API_KEY", "")
    with pytest.raises(SystemExit):
        planner_eval.run_live(planner_eval.load_dataset()[:1], 0)


def test_error_text_never_leaks_the_api_key(monkeypatch):
    monkeypatch.setattr(orchestrator, "GEMINI_API_KEY", "secret-key-123")
    assert "secret-key-123" not in planner_eval._redact("400 for url ...?key=secret-key-123")
