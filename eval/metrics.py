"""Pure scoring functions for planner output. No network, no orchestrator state."""

import re

from orchestrator import EXECUTABLE_AGENTS, PLANNER_AGENTS

# One pattern per agent, taken from the formats in PLANNER_PROMPT_TEMPLATE.
FORMAT_PATTERNS = {
    "KnowledgeAgent": re.compile(
        r"""^(add knowledge:\s*['"].+['"].*\bin\s+\w+|what is\s+.+\?)\s*$""",
        re.IGNORECASE | re.DOTALL,
    ),
    "SearchAgent": re.compile(r"^search for\s+\S.*$", re.IGNORECASE | re.DOTALL),
    "SlackAgent": re.compile(r'^post\s+"(.+)"\s+to\s+#[^\s]+$', re.IGNORECASE | re.DOTALL),
    "CalendarAgent": re.compile(r"^schedule\s+.+\s+for\s+\S.*$", re.IGNORECASE | re.DOTALL),
    "CommunicationAgent": re.compile(r"^send sms to\s+\S+:\s*\S.*$", re.IGNORECASE | re.DOTALL),
}

BOOL_METRICS = (
    "parse_ok", "schema_ok", "agents_valid", "format_ok",
    "exact_agent_set", "exact_sequence", "executable",
)


def normalize_plan(plan):
    """Mirror TaskOrchestrator.execute_plan: a single object becomes a one-step list."""
    return plan if isinstance(plan, list) else [plan]


def _schema_ok(plan):
    return isinstance(plan, list) and all(
        isinstance(s, dict)
        and isinstance(s.get("agent"), str)
        and isinstance(s.get("action"), str)
        for s in plan
    )


def score_case(case, plan, parse_ok):
    """Score one planner output.

    plan: the normalized parsed plan, or None when parsing failed.
    parse_ok: True when the real _gemini_request path produced a plan.

    Precision and recall compare the set of planned agents with expected_agents.
    When nothing was planned, precision is 1.0 only if nothing was expected;
    when nothing was expected, recall is 1.0. A failed parse scores 0 for both.
    """
    expected = list(case["expected_agents"])
    schema_ok = parse_ok and _schema_ok(plan)
    agents = [s["agent"] for s in plan] if schema_ok else []
    agents_valid = schema_ok and all(a in PLANNER_AGENTS for a in agents)
    format_ok = agents_valid and all(
        FORMAT_PATTERNS[s["agent"]].match(s["action"].strip()) for s in plan
    )
    executable = schema_ok and all(a in EXECUTABLE_AGENTS for a in agents)

    if not parse_ok or not schema_ok:
        precision = recall = 0.0
    else:
        predicted, wanted = set(agents), set(expected)
        hits = len(predicted & wanted)
        precision = hits / len(predicted) if predicted else (1.0 if not wanted else 0.0)
        recall = hits / len(wanted) if wanted else 1.0

    return {
        "id": case["id"],
        "category": case["category"],
        "parse_ok": bool(parse_ok),
        "schema_ok": bool(schema_ok),
        "agents_valid": bool(agents_valid),
        "format_ok": bool(format_ok),
        "agent_precision": precision,
        "agent_recall": recall,
        "exact_agent_set": bool(schema_ok and set(agents) == set(expected)),
        "exact_sequence": bool(schema_ok and agents == expected),
        "executable": bool(executable),
        "predicted_agents": agents,
        "expected_agents": expected,
    }


def _summarize(rows):
    n = len(rows)
    out = {"n": n}
    for key in BOOL_METRICS:
        out[key] = sum(r[key] for r in rows) / n if n else None
    for key in ("agent_precision", "agent_recall"):
        out[key] = sum(r[key] for r in rows) / n if n else None
    return out


def aggregate(rows):
    """Overall and per-category rates, with n next to every group."""
    by_category = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)
    return {
        "overall": _summarize(rows),
        "by_category": {c: _summarize(rs) for c, rs in sorted(by_category.items())},
    }
