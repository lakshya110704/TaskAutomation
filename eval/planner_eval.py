"""Planner evaluation: score the plans the model produces for eval/dataset.jsonl.

  python eval/planner_eval.py --mock              offline, scripted fake model
  python eval/planner_eval.py --replay RAW.jsonl  rescore saved model outputs offline
  python eval/planner_eval.py --live              call the real planner (GEMINI_API_KEY)

Every mode parses model text through the real TaskOrchestrator._gemini_request path.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import orchestrator  # noqa: E402
from eval.metrics import BOOL_METRICS, aggregate, normalize_plan, score_case  # noqa: E402

DATASET = os.path.join(ROOT, "eval", "dataset.jsonl")
RESULTS = os.path.join(ROOT, "eval", "results")

EXAMPLE_ACTIONS = {
    "KnowledgeAgent": "What is the answer?",
    "SearchAgent": "Search for the topic",
    "SlackAgent": 'Post "hello" to #general',
    "CalendarAgent": "Schedule the event for tomorrow",
    "CommunicationAgent": "Send SMS to +15550001111: hello",
}


class _FakeResponse:
    def __init__(self, text):
        self._text = text

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


def load_dataset(path=DATASET):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _new_orchestrator():
    # The real __init__ needs Slack and Google credentials; the parsing path does not.
    orch = object.__new__(orchestrator.TaskOrchestrator)
    if not orchestrator.GEMINI_API_KEY:
        orchestrator.GEMINI_API_KEY = "offline-placeholder"
    return orch


async def parse_model_text(text):
    """Run saved model text through the real _gemini_request. Returns (plan, error)."""
    orch = _new_orchestrator()
    orch._post_to_gemini = lambda payload: _FakeResponse(text)
    try:
        plan = await orch._gemini_request({"user_prompt": "x"}, "{user_prompt}")
        return normalize_plan(plan), None
    except Exception as e:  # json errors, bad response shape
        return None, f"{type(e).__name__}: {e}"


def _redact(message):
    key = orchestrator.GEMINI_API_KEY
    return message.replace(key, "REDACTED") if key else message


def run_live(cases, sleep_s):
    if not os.getenv("GEMINI_API_KEY") and not orchestrator.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set (env or .env). Use --mock or --replay offline.")
    orch = object.__new__(orchestrator.TaskOrchestrator)
    captured = []

    def recording_post(payload):
        resp = orchestrator.TaskOrchestrator._post_to_gemini(orch, payload)
        captured.append(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
        return resp

    orch._post_to_gemini = recording_post
    records = []
    for i, case in enumerate(cases):
        captured.clear()
        raw, error = None, None
        try:
            asyncio.run(orch._gemini_request(
                {"user_prompt": case["prompt"]}, orchestrator.PLANNER_PROMPT_TEMPLATE))
        except Exception as e:
            error = _redact(f"{type(e).__name__}: {e}")
        if captured:
            raw = captured[-1]
        records.append({
            "id": case["id"], "prompt": case["prompt"], "raw_text": raw,
            "api_error": error if raw is None else None, "source": "live",
        })
        print(f"[{i + 1}/{len(cases)}] {case['id']}: {'ok' if raw is not None else 'API ERROR'}")
        if i < len(cases) - 1:
            time.sleep(sleep_s)
    return records


def mock_records(cases):
    """Scripted fake model. Only proves the scoring pipeline; says nothing about a real model."""
    records = []
    for i, case in enumerate(cases):
        plan = [{"agent": a, "action": EXAMPLE_ACTIONS[a]} for a in case["expected_agents"]]
        mode = i % 6
        if mode == 0:
            text = json.dumps(plan)
        elif mode == 1:
            text = "```json\n" + json.dumps(plan) + "\n```"
        elif mode == 2:
            text = json.dumps([{"agent": "EmailAgent", "action": "Send email"}] + plan)
        elif mode == 3:
            text = json.dumps(plan + [{"agent": "SlackAgent", "action": "tell the channel hi"}])
        elif mode == 4:
            text = "Sure, here is the plan:\n" + json.dumps(plan)
        else:
            text = '[{"agent": "SlackAgent", "action": '
        records.append({"id": case["id"], "prompt": case["prompt"], "raw_text": text,
                        "api_error": None, "source": "mock"})
    return records


def score_records(cases, records):
    by_id = {r["id"]: r for r in records}
    rows, api_errors = [], 0
    for case in cases:
        rec = by_id.get(case["id"])
        if rec is None:
            continue
        if rec.get("raw_text") is None:
            api_errors += 1
            row = score_case(case, None, False)
            row["error"] = rec.get("api_error")
        else:
            plan, error = asyncio.run(parse_model_text(rec["raw_text"]))
            row = score_case(case, plan, plan is not None)
            row["error"] = error
        rows.append(row)
    return rows, api_errors


def _pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


COLUMNS = [("parse_ok", "parse"), ("schema_ok", "schema"), ("agents_valid", "valid agents"),
           ("format_ok", "format"), ("agent_precision", "precision"),
           ("agent_recall", "recall"), ("exact_agent_set", "exact set"),
           ("exact_sequence", "exact seq"), ("executable", "executable")]


def format_table(agg):
    header = ["category", "n"] + [label for _, label in COLUMNS]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    groups = list(agg["by_category"].items()) + [("OVERALL", agg["overall"])]
    for name, g in groups:
        cells = [name, str(g["n"])] + [_pct(g[k]) for k, _ in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(mode, rows, agg, api_errors, raw_name):
    mock = mode == "mock"
    out = []
    if mock:
        out += ["# MOCK, not model performance", "",
                "These rates come from a scripted fake model that only exercises the scoring "
                "pipeline. They say nothing about how Gemini plans.", ""]
    else:
        out += ["# Planner evaluation", ""]
    out += [f"- mode: {mode}", f"- raw outputs: {raw_name}",
            f"- cases scored: {len(rows)}", f"- API errors (no model text): {api_errors}",
            f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
            "Rates are over all cases in the group (n shown). A failed parse counts as 0.",
            "", format_table(agg), ""]
    misses = [r for r in rows if not r["exact_agent_set"] or not r["parse_ok"]]
    if misses:
        out += ["## Cases without an exact agent set", "",
                "| id | expected | predicted | note |", "|---|---|---|---|"]
        for r in misses:
            note = r.get("error") or ("invalid agent" if not r["agents_valid"] else "")
            out.append(f"| {r['id']} | {r['expected_agents']} | {r['predicted_agents']} | "
                       f"{str(note)[:80].replace('|', '/')} |")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--replay", metavar="RAW_JSONL")
    g.add_argument("--mock", action="store_true")
    ap.add_argument("--sleep", type=float, default=5.0, help="seconds between live calls")
    ap.add_argument("--limit", type=int, help="only the first N cases (live)")
    args = ap.parse_args()

    cases = load_dataset()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(RESULTS, exist_ok=True)

    if args.mock:
        mode, prefix, records = "mock", "mock_", mock_records(cases)
        raw_path = os.path.join(RESULTS, f"mock_raw_{ts}.jsonl")
        write_jsonl(raw_path, records)
    elif args.replay:
        records = load_jsonl(args.replay)
        mode = "replay"
        prefix = "mock_" if all(r.get("source") == "mock" for r in records) else ""
        raw_path = args.replay
        if prefix:
            mode = "mock"
    else:
        if args.limit:
            cases = cases[: args.limit]
        records = run_live(cases, args.sleep)
        mode, prefix = "live", ""
        raw_path = os.path.join(RESULTS, f"raw_{ts}.jsonl")
        write_jsonl(raw_path, records)

    rows, api_errors = score_records(cases, records)
    agg = aggregate(rows)
    report = build_report(mode, rows, agg, api_errors, os.path.basename(raw_path))
    report_path = os.path.join(RESULTS, f"{prefix}report_{ts}.md")
    summary_path = os.path.join(RESULTS, f"{prefix}summary_{ts}.json")
    with open(report_path, "w") as f:
        f.write(report)
    with open(summary_path, "w") as f:
        json.dump({"mode": mode, "raw": os.path.basename(raw_path), "api_errors": api_errors,
                   "aggregate": agg, "cases": rows}, f, indent=2)
    print(report)
    print(f"\nwrote {report_path}\nwrote {summary_path}")


if __name__ == "__main__":
    main()
