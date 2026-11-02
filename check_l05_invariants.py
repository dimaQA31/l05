"""Offline checks of saved observations; no live model or external API calls.

Run: python3 check_l05_invariants.py
Missing probe mentions are reported as missing evidence for historical replies.
The current JSONL case checks four entities; this legacy replay covers amount and code only.
"""
import json
from pathlib import Path

import assertions as A
from loader import load

HERE = Path(__file__).resolve().parent


def evaluate(answers, baseline, inv):
    """Compare all extracted values with the independently observed baseline."""
    if baseline is None:
        return {"status": "not_applicable", "reason": "no selected baseline value"}
    probes = {}
    for turn in inv["probe_turns"]:
        answer = answers.get(str(turn), "")
        values = A.extracted_values(answer, inv["value_pattern"])
        if not values:
            probes[str(turn)] = {"status": "missing_evidence"}
            continue
        verdict = A.extracted_invariant(
            answer, inv["value_pattern"], baseline,
            numeric=inv["level"] == 2,
            tolerance=inv.get("tolerance", 0.01),
            canonical_code=inv.get("canonical_code", False))
        probes[str(turn)] = {"status": "pass" if verdict.passed else "fail",
                             "values": values, "detail": verdict.detail}
    statuses = [p["status"] for p in probes.values()]
    status = ("fail" if "fail" in statuses else
              "incomplete" if "missing_evidence" in statuses else "pass")
    return {"status": status, "baseline": baseline, "probes": probes}


def main():
    raw = next(json.loads(line) for line in (HERE / "l05_dialogs.jsonl").read_text().splitlines()
               if line.strip() and json.loads(line)["id"] == "CONV-002")
    invs = raw["additional_metadata"]["invariants"]
    load(HERE / "l05_dialogs.jsonl")  # Validate the runnable prospective case.
    result = {"mode": "offline_replay", "note": "Historical prompts differ from the prospective case.",
              "runs": {}}
    for filename in ("l05-clean-20261027T123708.json", "l05-lesson-05-20261027T123840.json"):
        report = json.loads((HERE / "reports" / filename).read_text())
        case = next(c for c in report["cases"] if c["id"] == "CONV-002")
        answers = {str(t["turn"]): t["answer"] for t in case["transcript"]}
        baseline_codes = A.extracted_values(answers["2"], invs[1]["value_pattern"])
        # The reported baseline must select exactly one distinct code.
        unique_codes = {v.lower().replace(" ", "_") for v in baseline_codes}
        code = next(iter(unique_codes)) if len(unique_codes) == 1 else None
        result["runs"][filename] = {
            "dispute_amount": evaluate(answers, 240.0, invs[0]),
            "reason_code": evaluate(answers, code, invs[1])}
    obs = json.loads((HERE / "reports/evidence/0fe8ca607d4c/invariant-observations.json").read_text())
    result["runs"][obs["session_id"]] = {
        "evidence": "Annotated transcript excerpts",
        "dispute_amount": evaluate(obs["answers"], 240.0, invs[0]),
        "reason_code": evaluate(obs["answers"], obs["baseline_reason_code"], invs[1])}
    path = HERE / "reports/l05-invariant-replay.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for run, values in result["runs"].items():
        print(run, {key: value["status"] for key, value in values.items() if isinstance(value, dict)})
    print(path)


if __name__ == "__main__":
    main()
