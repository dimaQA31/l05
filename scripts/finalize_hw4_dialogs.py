"""Summarize the two completed hw4 runs; never call the stand or model."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import runner
from loader import load, set_hash

path = ROOT / 'sets/l05_dialogs.jsonl'
cases = load(path)
case_hash = set_hash(path)
records = {}
paths = {}
for profile in ['clean', 'lesson-05']:
    choices = []
    for report_path in (ROOT / 'reports').glob(f'l05_dialogs-{profile}-*.json'):
        report = json.loads(report_path.read_text())
        if report.get('set_hash') == case_hash:
            choices.append((report['ran_at'], report_path, report))
    if not choices:
        raise SystemExit(f'No completed {profile} report for hash {case_hash}')
    _, paths[profile], records[profile] = max(choices)
    assert len(records[profile]['cases']) == 5

summary = {'set_hash': case_hash, 'forecast_commit': '6ea4cee', 'profiles': {}}
for profile, report in records.items():
    entries = {}
    agent_steps = llm_calls = summarizer_calls = 0
    for case in cases:
        row = next(r for r in report['cases'] if r['id'] == case['id'])
        traces_dir = ROOT / row['traces_dir']
        repeats = []
        entity_failures = {i['entity']: 0 for i in case['additional_metadata']['invariants']}
        for repeat in range(1, 6):
            saved = [json.loads((traces_dir / f"{case['id']}-run{repeat}-turn{t}.json").read_text())
                     for t in range(1, len(case['turns']) + 1)]
            run = {'turns': [{'answer': x['answer'], 'trace': x['trace']} for x in saved]}
            agent_steps += len(saved)
            for step in saved:
                for span in runner.stand.spans(step['trace']):
                    llm_calls += span['name'] == 'llm.call'
                    summarizer_calls += span['name'] == 'agent.summarize'
            verdict = runner._dialog_run(case, run)
            failures = [c for c in verdict.checks if not c['passed']]
            for entity in entity_failures:
                if any(not c['passed'] and c['label'] == f'{entity} still holds' for c in verdict.checks):
                    entity_failures[entity] += 1
            repeats.append({'run': repeat, 'passed': verdict.passed,
                            'profile': saved[0]['trace']['attributes']['run.profile'],
                            'baseline_failed': any(c['precondition'] for c in failures),
                            'unreadable_json_field': any(
                                c['assertion'].startswith('json_') and 'extracted []' in c['detail']
                                for c in failures),
                            'failures': failures})
        assert all(r['profile'] == ('clean' if case['id'] == 'CONV-002-CLEAN' else profile)
                   for r in repeats)
        entries[case['id']] = {'passed': sum(r['passed'] for r in repeats),
                               'total': 5, 'entity_probe_failures': entity_failures,
                               'baseline_failures': sum(r['baseline_failed'] for r in repeats),
                               'unreadable_json_repeats': sum(r['unreadable_json_field'] for r in repeats),
                               'repeats': repeats, 'traces_dir': row['traces_dir']}
    summary['profiles'][profile] = {'report': str(paths[profile].relative_to(ROOT)),
                                    'cases_passed': sum(x['passed'] == 5 for x in entries.values()),
                                    'repeats_passed': sum(x['passed'] for x in entries.values()),
                                    'agent_steps': agent_steps,
                                    'llm_calls': llm_calls,
                                    'summarizer_calls': summarizer_calls,
                                    'provider_calls': llm_calls + summarizer_calls,
                                    'cases': entries}
summary['forecast_review'] = {}
for case in cases:
    observed = summary['profiles']['lesson-05']['cases'][case['id']]
    failures = [min(f['turn'] for f in r['failures'] if isinstance(f['turn'], int))
                for r in observed['repeats'] if r['failures']]
    summary['forecast_review'][case['id']] = {
        'predicted_first_probe': case['additional_metadata']['invariants'][0]['probe_turns'][0],
        'observed_first_failure_turns': failures,
        'actual_profile': observed['repeats'][0]['profile']}
output = ROOT / 'reports/hw4-dialogs-summary.json'
output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')

p = ROOT / 'multi-turn-test-plan.md'
s = p.read_text()
a = s.index('### 4.1.'); b = s.index('## 5.', a)
clean = summary['profiles']['clean']; lesson = summary['profiles']['lesson-05']
cm = clean['cases']['CONV-002']; lm = lesson['cases']['CONV-002']
treatment = [v for k, v in lesson['cases'].items() if k != 'CONV-002-CLEAN']
unreadable_count = sum(v['unreadable_json_repeats'] for v in treatment)
treatment_passed = sum(v['passed'] for v in treatment)
treatment_failed = sum(v['total'] - v['passed'] for v in treatment)
readable_failures = treatment_failed - unreadable_count
baseline_passed = sum(len(v['repeats']) - v['baseline_failures']
                      for profile in summary['profiles'].values() for v in profile['cases'].values())
rows = []
for case in cases:
    m = case['additional_metadata']; cid = case['id']
    invariants = '; '.join(f"{i['entity']} · з {i['from_turn']} · L{i['level']}" for i in m['invariants'])
    oracles = '; '.join(f"{i['entity']}: крок {i['oracle_turn']} — {i['oracle_by']}" for i in m['invariants'])
    c = clean['cases'][cid]; l = lesson['cases'][cid]
    profile_note = ' (фактично clean)' if cid == 'CONV-002-CLEAN' else ''
    rows.append(f"| {cid} | {invariants} | {oracles} | {c['passed']}/5 | {l['passed']}/5{profile_note} |")
links = f"[clean]({clean['report']}), [lesson-05]({lesson['report']}), [покроковий розбір](reports/hw4-dialogs-summary.json)"
section = f'''### 4.1. Дві перевірки для основного сценарію

Поточна редакція CONV-002 встановлює параметри справи на кроках 1–2 і перевіряє їх на 5, 6, 7 після тем лімітів та FX. Значення читаються з окремих JSON-полів; умовна альтернатива у поясненні поза JSON не змінює обраний reason_code. Oracle-значення незалежні від першої відповіді агента.

| Перевірка | Сутність | З кроку | Рівень | clean: порушення інваріанта | lesson-05: порушення інваріанта |
| --- | --- | --- | --- | --- | --- |
| 1 | amount=240.00 EUR ±0.01 | 1 | 2 — число з допуском | {cm['entity_probe_failures']['dispute_amount']}/5 | {lm['entity_probe_failures']['dispute_amount']}/5 |
| 2 | reason_code=goods_not_received | 2 | 1 — точна рівність | {cm['entity_probe_failures']['reason_code']}/5 | {lm['entity_probe_failures']['reason_code']}/5 |

Ці частки стосуються саме пізніших інваріантних проб, а не всіх причин падіння кейса. Початкові передумови не пройшли у {cm['baseline_failures']}/5 clean і {lm['baseline_failures']}/5 lesson-05 повторів; oracle, дата, вікно та заборона дії оцінюються окремо. Повністю зелений CONV-002: clean {cm['passed']}/5, lesson-05 {lm['passed']}/5. Вихідні звіти: {links}.

У кейсі також перевіряються transaction_date=2026-07-20 та filing_window_days=90, обидва рівня 1, з незалежними джерелами з банківської фікстури й правил спорів. Одна правильна сума у фіналі не скасовує помилку на проміжній пробі. Втрата поля у вхідній історії — окрема метрика з розділу 2; звіти цього запуску оцінюють відповідь і tool results, а не стверджують збереження прихованої пам’яті.

### 4.2. Інваріанти й оракули всіх кейсів

[Набір](sets/l05_dialogs.jsonl): **5 кейсів**, added_in=hw4, runs=5, gate=release, set_hash `{case_hash}`. Основний, короткий, довгий і clean-контроль мають чотири інваріанти; ONE-ENTITY — лише суму. Контрольний кейс завжди виконується на clean через context.profile, після повтору попередній профіль відновлюється.

| Кейс | Інваріанти: сутність · початок · рівень | Оракули: перша поява · джерело правильності | clean: пройшли | запуск lesson-05: пройшли |
| --- | --- | --- | --- | --- |
''' + '\n'.join(rows) + f'''

**Загальний результат:** clean — {clean['cases_passed']}/5 повністю зелених кейсів, {clean['repeats_passed']}/25 успішних повторів; запуск lesson-05 — {lesson['cases_passed']}/5 кейсів, {lesson['repeats_passed']}/25 повторів. Lesson-запуск містить 4 сценарії на lesson-05 та 1 контроль на clean, а не 25 lesson-05 розмов. Дані та точні причини падінь: {links}.

**Обмеження формату.** У SHORT на lesson-05 у {lesson['cases']['CONV-002-SHORT']['unreadable_json_repeats']}/5 повторів контрольна відповідь не містить читабельного JSON-поля: JSON обірваний або не сформований. Ці запуски червоні за контрактом кейса, але відсутність прочитаного поля не доводить саме підміну його значення. Не трактуємо всі спрацювання reason_code у SHORT як чистий D07: окремо розбираються формат і вміст summary/tool results. Загалом із 20 lesson-05 розмов {readable_failures} мають провали значень у читабельних полях, {unreadable_count} — нечитабельний JSON на контрольній пробі, {treatment_passed} пройшли.

**Оракули до стабільності.** Для чотирьох кейсів початкові tool checks звіряють 240 EUR саме з рядком TX-0401/EUR, аргументи eligibility — з явною недоставкою фізичного товару, код — з goods_not_received і вікно — з 90 днями. Дата порівнюється з незалежною датою фікстури, а не з першою відповіддю. Для ONE-ENTITY еталон 240 заданий прямо клієнтом і зафіксований як expected_number; транзакції та eligibility не витягуються, щоб не змішувати одну сутність із повною справою.

**Узгоджена помилка.** Стабільні 180 EUR від початку до кінця не проходять незалежний oracle=240. Стабільні 120 днів для goods_not_received не проходять oracle=90. Успішна eligibility-перевірка під іншим кодом не доводить правильності вибору причини: перевіряються і її аргументи, і задана клієнтом ситуація. Червоний baseline або невиконаний oracle не прирівнюються автоматично до доведеної втрати на кроці 3.

**Історичні варіанти.** Старі оцінки ручних діалогів, де еталон причини не завжди був встановлений, збережені в [архіві](reports/hw4-documents-before-formal-runs.md). Вони не підміняють п’ять повторів поточної редакції. Старий regex-екстрактор лишається для replay тих транскриптів; поточні кейси перевіряють конкретні JSON-значення й не трактують будь-яку згадку іншого коду як зміну обраного.

**Відтворення.** docker compose run --rm eval --set l05_dialogs --dry-run; живі запуски описані в README. [Підсумовувач](scripts/finalize_hw4_dialogs.py) повторно оцінює збережені трейси без LLM-викликів. Перевірки відсутності create_dispute та заборони transaction lookup у ONE-ENTITY входять у кейси й можуть дати окрему причину червоного результату.

---

'''
s = s[:a] + section + s[b:]
s = re.sub(r'набір\s+l05_dialogs.jsonl, \d+ кейс\w* · set_hash \w+',
           f'набір               l05_dialogs.jsonl, 5 кейсів · set_hash {case_hash}', s, count=1)
s = s.replace('прогрес та результати відокремлені від попередніх лабораторних вимірювань',
              'обидва формальні запуски завершені, їхні результати наведено у 4.2 окремо від попередніх лабораторних вимірювань')
s = s.replace('**Умови перевірки виправлення.** Оформити п’ять кейсів із розділу 5 у JSONL, додати інваріанти всіх потрібних полів і незалежні оракули, виконати п’ять повторів кожного зі сталим початковим станом.',
              '**Умови перевірки виправлення.** П’ять кейсів із розділу 5, потрібні інваріанти й оракули оформлено у JSONL та перевірено на базовому стенді. Після реалізації структурованого стану повторити п’ять прогонів кожного зі сталим початковим станом; поточні звіти не доводять ефект ще не реалізованого виправлення.')
cost_marker = '**Виміряна ціна формальних запусків.**'
if cost_marker not in s:
    anchor = '**Порівняння з однокроковим golden.jsonl.**'
    cost_note = (f'{cost_marker} Clean — {clean["agent_steps"]} кроків, '
                 f'{clean["llm_calls"]} llm.call + {clean["summarizer_calls"]} '
                 f'agent.summarize = {clean["provider_calls"]} записаних викликів провайдера; '
                 f'lesson-запуск — {lesson["agent_steps"]} кроків, {lesson["llm_calls"]} + '
                 f'{lesson["summarizer_calls"]} = {lesson["provider_calls"]}. Разом 360 кроків '
                 f'і {clean["provider_calls"] + lesson["provider_calls"]} логічних викликів. '
                 'Оцінка 417 на один запуск залишена як попередній бюджет; фактичні числа '
                 'походять зі збережених трейсів, а не з припущення «один крок = одна модель».\n\n')
    s = s.replace(anchor, cost_note + anchor, 1)
for item in ['У розділі 1 записано прогноз', 'У 4.1 дві перевірки з результатом на `clean` і `lesson-05`',
             'У розділі 1 заповнено всі рядки, зокрема кількість кейсів і `set_hash`']:
    s = s.replace('- [ ] ' + item, '- [x] ' + item)
p.write_text(s)

readme = ROOT / 'README.md'; r = readme.read_text()
marker = '\n## ДЗ_4: результати формальних прогонів\n'
if marker in r:
    r = r.split(marker, 1)[0]
result_rows = '\n'.join(f"| {c['id']} | {clean['cases'][c['id']]['passed']}/5 | {lesson['cases'][c['id']]['passed']}/5 |"
                        for c in cases)
r += marker + f'''
Набір `{case_hash}` перевірений після прогнозу з окремого коміту `6ea4cee`.
Репліки та очікування між профілями не змінювалися. По 5 повторів кожного
кейса на запуск; обидва запуски — 360 кроків. Контроль CLEAN закріплений
на clean в обох запусках, фактичний профіль зазначено в execution_profile.

| Кейс | clean: успішні повтори | запуск lesson-05: успішні повтори |
|---|---|---|
{result_rows}

Звіти: {links}. Значення в таблиці — вимірювання, а не заміна прогнозу вище.
Причини й контрольні кроки кожного падіння записані у hw4-dialogs-summary.json.
Відсутність провалу відповіді не доводить збереження поля у прихованій історії.

Прогноз першого прояву підтвердився у червоних повторах: CONV-002, SHORT
і ONE-ENTITY — крок 5; LONG-SEPA — крок 8. Основний кейс пройшов {lm['passed']}/5
повторів на lesson-05, тому прогноз не трактуємо як детерміноване падіння.
У основному кейсі код пройшов {5-lm['entity_probe_failures']['reason_code']}/5 повторів.
Початкові передумови пройшли в {baseline_passed}/50 розмовах.
У {lesson['cases']['CONV-002-SHORT']['unreadable_json_repeats']} червоних повторах SHORT є неповний/нечитабельний JSON: це окрема
причина невиконання контракту, їх не зараховуємо як доказ чистого D07.

Виміряна ціна: 180 кроків / {clean['provider_calls']} викликів провайдера для clean,
180 / {lesson['provider_calls']} для lesson-запуску (llm.call + agent.summarize).
Це 360 кроків і {clean['provider_calls'] + lesson['provider_calls']} записаних викликів загалом.
'''
readme.write_text(r)
print(json.dumps({p: {'cases_passed': d['cases_passed'], 'repeats_passed': d['repeats_passed']}
                  for p, d in summary['profiles'].items()}, ensure_ascii=False))
