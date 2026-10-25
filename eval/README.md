# Evaluation harness

Measures how well the planner (Gemini) turns a request into a valid, executable plan,
and how the retry policy behaves when the services behind the agents fail.

## Run

```bash
pip install -r requirements.txt -r requirements-dev.txt

python eval/planner_eval.py --mock                   # offline, scripted fake model
python eval/planner_eval.py --replay eval/results/raw_<timestamp>.jsonl   # rescore, offline
GEMINI_API_KEY=... python eval/planner_eval.py --live [--sleep 5] [--limit N]
python eval/failure_injection.py                     # retry policy, offline
pytest                                               # unit tests for all of the above
```

Outputs go to `eval/results/`: `raw_<ts>.jsonl` (model text, live only), `report_<ts>.md`,
`summary_<ts>.json`. Mock outputs are prefixed `mock_` and git-ignored. `--live` reads the
key from the environment or `.env`; API error text is redacted so the key never reaches a file.

## Modes

- `--live` calls the real planner once per case with a pause between calls, saves the raw
  model text, then scores it.
- `--replay` rescores saved raw text with no network, so a published number can be re-checked.
- `--mock` uses a scripted fake model (clean JSON, fenced JSON, invented agent, bad format,
  prose, truncated JSON). It only proves the scoring pipeline works. Its report starts with
  "MOCK, not model performance".

All modes send model text through the real `TaskOrchestrator._gemini_request`, so fence
stripping and JSON parsing are the production code path.

## Dataset

`dataset.jsonl` has 30 cases, 6 per category: `single_tool`, `multi_tool` (order matters),
`ambiguous`, `unsupported` (expected plan is empty, the planner should not invent an agent)
and `injection` (the prompt tries to add steps or break the format; expected agents are only
the legitimate ones). `expected_agents` is an ordered list.

## Metrics (`metrics.py`)

| metric | meaning |
|---|---|
| parse_ok | model text parsed into JSON by the real path (a single object counts, as in `execute_plan`) |
| schema_ok | a list of steps, each with string `agent` and `action` |
| agents_valid | every agent is one of the five names in the planner prompt |
| format_ok | every action matches the format regex for its agent |
| agent_precision / agent_recall | set overlap of planned vs expected agents |
| exact_agent_set / exact_sequence | same set / same ordered list as expected |
| executable | every planned agent has a real executor (`CommunicationAgent` does not) |

Rates are over all cases in a group, and `n` is printed next to every row. A failed parse
scores 0 on everything. With an empty plan, precision is 1 only when nothing was expected;
with nothing expected, recall is 1.

## Failure injection

`failure_injection.py` raises errors below the retry decorators (Slack SDK, Google client,
`requests`, DuckDuckGo) and runs a four-step plan through `_execute_step`. The retry policy is
the real one with the waits removed. It reports, per scenario, attempts made and whether the
step completed, completed after a retry, or failed visibly.

## Limits

- 30 cases, one model, one prompt. Differences of a few cases are noise.
- Scores are heuristics. `ambiguous` expectations are one reasonable reading; a different
  sensible plan scores as wrong. Format regexes are stricter than what the executors accept.
- The harness scores plans, not whether Slack, Calendar or SMS actions succeed in the world.
- Failure injection simulates errors; it does not exercise real network behaviour.
