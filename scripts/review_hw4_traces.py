"""Read completed saved repeats without calling the model or stand."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runner
from loader import load

folder = Path(sys.argv[1])
cases = load(Path(__file__).resolve().parent.parent / 'sets/l05_dialogs.jsonl')
rows = []
for case in cases:
    repeats = []
    for repeat in range(1, 6):
        paths = [folder / f"{case['id']}-run{repeat}-turn{i}.json"
                 for i in range(1, len(case['turns']) + 1)]
        if not all(p.exists() for p in paths):
            continue
        try:
            saved = [json.loads(p.read_text()) for p in paths]
        except ValueError:
            continue
        run = {'turns': [{'answer': v['answer'], 'trace': v['trace']} for v in saved]}
        verdict = runner._dialog_run(case, run)
        failed = [{'turn': c['turn'], 'assertion': c['assertion'], 'label': c['label'],
                   'detail': c['detail'], 'precondition': c['precondition']}
                  for c in verdict.checks if not c['passed']]
        repeats.append({'run': repeat, 'passed': verdict.passed,
                        'profile': saved[0]['trace']['attributes']['run.profile'],
                        'failed': failed})
    rows.append({'id': case['id'], 'completed': len(repeats),
                 'passed': sum(r['passed'] for r in repeats), 'repeats': repeats})
print(json.dumps(rows, ensure_ascii=False, indent=2))
