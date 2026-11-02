"""Split full-input JSONL capture and compute the amount-loss distribution.

The first absent/corrupted 240 EUR in the actual agent history is loss; response
manifestations are reviewed separately, by entity, rather than inferred from a
request for clarification or from first_fail_turn of a generic assertion.
"""
import json
import re
import statistics
import sys
from pathlib import Path

folder = Path(sys.argv[1])
events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
assert events[-1]['event'] == 'completed', 'Capture has not completed'
meta = next(e for e in events if e['event'] == 'metadata')
steps = [e for e in events if e['event'] == 'step']
assert len(steps) == 35
correct = re.compile(r'(?<!\d)240(?:\.0{1,2})?(?!\d)')
summary = {'metadata': meta, 'runs': []}
sessions = set()
for run in range(1, 6):
    turns = [e for e in steps if e['run'] == run]
    assert [t['turn'] for t in turns] == list(range(1, 8))
    sid = turns[0]['session_id']; sessions.add(sid)
    run_dir = folder / f'run-{run}'
    run_dir.mkdir(exist_ok=True)
    losses = []
    for step in turns:
        assert step['session_id'] == sid
        assert step['trace']['attributes']['run.profile'] == 'lesson-05'
        calls = [c for c in step['model_calls'] if c['kind'] == 'agent']
        assert calls
        history = calls[0]['messages']
        present = bool(correct.search(json.dumps(history, ensure_ascii=False)))
        if step['turn'] > 1 and not present:
            losses.append(step['turn'])
        (run_dir / f"step-{step['turn']}.json").write_text(
            json.dumps(step, ensure_ascii=False, indent=2) + '\n')
    loss = min(losses) if losses else None
    loss_step = turns[loss - 1] if loss else None
    if loss_step:
        # Proof of a transition in the same session, not just summary omission.
        assert correct.search(json.dumps(loss_step['history_before']['messages'], ensure_ascii=False))
        assert any(c['kind'] == 'summarizer' for c in loss_step['model_calls'])
    summaries = [{'turn': t['turn'], **sp['attributes']}
                 for t in turns for sp in t['trace']['children'] if sp['name'] == 'agent.summarize']
    summary['runs'].append({'run': run, 'session_id': sid, 'amount_loss_turn': loss,
                            'summaries': summaries})
    (run_dir / 'run.json').write_text(json.dumps({'run': run, 'session_id': sid, 'turns': turns},
                                               ensure_ascii=False, indent=2) + '\n')
assert len(sessions) == 5
losses = [r['amount_loss_turn'] for r in summary['runs'] if r['amount_loss_turn'] is not None]
summary['amount_loss_distribution'] = {'values': sorted(losses), 'observed': len(losses),
                                      'total': 5, 'min': min(losses) if losses else None,
                                      'max': max(losses) if losses else None,
                                      'median': statistics.median(losses) if losses else None}
review_path = folder / 'manifestations.json'
if review_path.exists():
    summary['response_review'] = json.loads(review_path.read_text())
(folder / 'analysis.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary['amount_loss_distribution']))
