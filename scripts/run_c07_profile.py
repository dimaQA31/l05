"""Run inside the PayPilot container; emit JSONL evidence to stdout.

Uses the installed agent loop and provider unchanged, wrapping complete() only
for recording arguments/results. Configuration changes are process-local.
No server reset, source patches, mocked answers, or shared config changes.
"""
import argparse
import copy
import json
import sys
import traceback
from dataclasses import asdict
from datetime import datetime, timezone

from app import clock, config, defects, tracing
from app.agent import loop

TURNS = [
    "I'm CUS-0004. Give me reason code for transaction TX-0401 with amount 240.00 EUR.",
    "Can I dispute it?",
    "What is my daily card limit?",
    "And the FX spread if I pay in USD?",
    "Fine. Back to that charge — what do I do next?",
    "Amount 240 euro, as I said at the start.",
    "And I still have time to file, right?",
]
parser = argparse.ArgumentParser()
parser.add_argument('--profile', choices=['clean', 'lesson-05'], default='lesson-05')
parser.add_argument('--runs', type=int, default=5)
args = parser.parse_args()
if args.runs < 1:
    parser.error('--runs must be positive')
config.SUMMARIZE_AFTER_STEPS = 2
clock.set_override("2026-09-15T10:00:00Z")
defects.set_runtime_profile(args.profile)
defects.set_runtime_defects("")
original_get_provider = loop.get_provider
calls = []


class RecordingProvider:
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def complete(self, system, messages, tools):
        record = copy.deepcopy({"system": system, "messages": messages, "tools": tools,
                                "kind": "agent" if tools else "summarizer"})
        calls.append(record)
        response = self.inner.complete(system, messages, tools)
        record["response"] = asdict(response)
        return response


loop.get_provider = lambda: RecordingProvider(original_get_provider())


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


emit({"event": "metadata", "started_at": datetime.now(timezone.utc).isoformat(),
      "execution": "isolated process using installed agent loop, recording provider arguments",
      "profile": defects.describe(), "clock": clock.describe(),
      "summarize_after_steps": config.SUMMARIZE_AFTER_STEPS,
      "provider": config.LLM_PROVIDER, "model": config.LLM_MODEL,
      "turns": TURNS, "runs": args.runs})
assert config.LLM_PROVIDER != "mock", "A live provider is required"
assert defects.active() == ({"D06", "D07"} if args.profile == 'lesson-05' else set())
for run in range(1, args.runs + 1):
    sid = None
    for number, question in enumerate(TURNS, 1):
        calls.clear()
        before = copy.deepcopy(loop._sessions.get(("", sid), {"messages": [], "steps": 0}))
        try:
            response = loop.run_turn(sid, question, "CUS-0004")
            sid = response["session_id"]
            emit({"event": "step", "run": run, "turn": number, "session_id": sid,
                  "user": question, "answer": response["answer"], "response": response,
                  "history_before": before, "model_calls": calls,
                  "history_after": copy.deepcopy(loop._sessions[("", sid)]),
                  "trace": tracing.get(response["request_id"])})
        except Exception as error:
            emit({"event": "error", "run": run, "turn": number, "session_id": sid,
                  "error_type": type(error).__name__, "error": str(error),
                  "history_before": before, "model_calls": calls})
            traceback.print_exc(file=sys.stderr)
            raise
    emit({"event": "run_completed", "run": run, "session_id": sid})
emit({"event": "completed", "runs": args.runs})
