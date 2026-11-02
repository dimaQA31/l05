"""Regression tests for numeric and exact entity invariants (no model calls)."""
import copy
import json
import unittest
from unittest.mock import patch, call
from pathlib import Path

import assertions as A
import loader
import runner


class InvariantTests(unittest.TestCase):
    def setUp(self):
        self.case = next(json.loads(line) for line in Path('l05_dialogs.jsonl').read_text().splitlines()
                         if json.loads(line)['id'] == 'CONV-002')
        self.amount, self.code = self.case['additional_metadata']['invariants'][:2]

    def test_correct_amount_cannot_mask_corrupted_history(self):
        v = A.extracted_invariant('EUR 180.00 earlier; bank record EUR 240.00',
                                  self.amount['value_pattern'], 240, numeric=True)
        self.assertFalse(v.passed)
        self.assertEqual(v.level, 2)

    def test_numeric_tolerance_and_currency_positions(self):
        for reply in ['€240.00', '240.00 EUR', 'EUR 240.01']:
            with self.subTest(reply=reply):
                v = A.extracted_invariant(reply, self.amount['value_pattern'],
                                          240, numeric=True, tolerance=0.01)
                self.assertTrue(v.passed)
        self.assertFalse(A.extracted_invariant('EUR 240,000', self.amount['value_pattern'],
                                              240, numeric=True).passed)
        self.assertFalse(A.extracted_invariant('EUR 240.02', self.amount['value_pattern'],
                                              240, numeric=True).passed)

    def test_exact_canonical_code_and_changed_code(self):
        good = A.extracted_invariant('Reason: GOODS NOT RECEIVED',
                                     self.code['value_pattern'], 'goods_not_received',
                                     canonical_code=True)
        self.assertTrue(good.passed)
        self.assertEqual(good.level, 1)
        self.assertFalse(A.extracted_invariant('duplicate_charge', self.code['value_pattern'],
                                               'goods_not_received', canonical_code=True).passed)
        self.assertFalse(A.extracted_invariant('goods_not_received or service_not_rendered',
                                               self.code['value_pattern'], 'goods_not_received',
                                               canonical_code=True).passed)

    def test_missing_entity_is_not_a_pass_in_prospective_case(self):
        self.assertFalse(A.extracted_invariant('Daily limit information',
                                               self.amount['value_pattern'], 240,
                                               numeric=True).passed)

    def test_compile_and_execute_both_levels_with_baseline_guard(self):
        case = copy.deepcopy(self.case)
        loader._validate(case, 'test')
        checks = case['additional_metadata']['checks']
        self.assertTrue(any(c['assertion'] == 'json_exact' for c in checks))
        data = {'amount': 240, 'transaction_id': 'TX-0401', 'currency': 'EUR',
                'transaction_date': '2026-07-20', 'reason_code': 'goods_not_received',
                'filing_window_days': 90}
        turns = [{'answer': json.dumps(data), 'trace': {
                    'name': 'agent.request', 'children': [{
                        'name': 'tool.get_transactions', 'attributes': {
                            'tool.result': {'transactions': [
                                {'id': 'TX-0401', 'amount': 240, 'currency': 'EUR'}]}}}]}},
                 {'answer': json.dumps(data), 'trace': {
                    'name': 'agent.request', 'children': [{
                        'name': 'tool.check_dispute_eligibility', 'attributes': {
                            'tool.arguments': {'transaction_id': 'TX-0401',
                                               'reason_code': 'goods_not_received'},
                            'tool.result': {'reason_code': 'goods_not_received',
                                            'window_days': 90}}}]}},
                 {'answer': 'limits', 'trace': {'name': 'agent.summarize'}},
                 {'answer': 'FX'}, *[{'answer': json.dumps(data)} for _ in range(3)]]
        self.assertTrue(runner._dialog_run(case, {'turns': turns}).passed)
        turns[4]['answer'] = json.dumps({**data, 'amount': 180})
        verdict = runner._dialog_run(case, {'turns': turns})
        self.assertFalse(verdict.passed)
        self.assertTrue(any(c['level'] == 2 and not c['passed'] for c in verdict.checks))
        turns[1]['answer'] = 'Tell me the reason first'
        self.assertEqual(runner._dialog_run(case, {'turns': turns}).assertion, 'precondition')

    def test_json_selected_code_ignores_alternative_in_prose(self):
        reply = 'Alternative: service_not_rendered. Selected: {"reason_code":"goods_not_received"}'
        self.assertTrue(A.json_entity_invariant(reply, 'reason_code', 'goods_not_received').passed)
        self.assertFalse(A.json_entity_invariant('{"reason_code":"service_not_rendered"}',
                                                 'reason_code', 'goods_not_received').passed)
        self.assertFalse(A.json_entity_invariant('{"amount":true}', 'amount', 1,
                                                 numeric=True).passed)
        self.assertFalse(A.json_entity_invariant('{"amount":240}{"amount":180}',
                                                 'amount', 240, numeric=True).passed)

    def test_control_profile_is_restored_after_error(self):
        with patch.object(runner.stand, 'profile', return_value={'profile': 'lesson-05'}), \
             patch.object(runner.stand, 'set_profile') as set_profile, \
             patch.object(runner, '_one_run_body', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                runner._one_run({'context': {'profile': 'clean'}})
            self.assertEqual(set_profile.call_args_list, [call('clean'), call('lesson-05')])

    def test_oracle_selects_transaction_and_currency(self):
        trace = {'name': 'tool.get_transactions', 'attributes': {'tool.result': {
            'transactions': [{'id': 'TX-0402', 'currency': 'EUR', 'amount': 240},
                             {'id': 'TX-0401', 'currency': 'USD', 'amount': 240},
                             {'id': 'TX-0401', 'currency': 'EUR', 'amount': 180}]}}}
        verdict = A.tool_result_row_numeric(trace, 'get_transactions', 'transactions',
                                            {'id': 'TX-0401', 'currency': 'EUR'},
                                            'amount', 240)
        self.assertFalse(verdict.passed)
        trace['attributes']['tool.result']['transactions'][-1]['amount'] = 240
        self.assertTrue(A.tool_result_row_numeric(
            trace, 'get_transactions', 'transactions',
            {'id': 'TX-0401', 'currency': 'EUR'}, 'amount', 240).passed)

    def test_consistently_wrong_value_cannot_pass_oracle(self):
        for answer in ['EUR 180.00', 'EUR 180.00', 'EUR 180.00']:
            self.assertFalse(A.extracted_invariant(
                answer, self.amount['value_pattern'], 240, numeric=True).passed)
        # Independent bank oracle also rejects a fixture that is wrong from the start.
        trace = {'name': 'tool.get_transactions', 'attributes': {'tool.result': {
            'transactions': [{'id': 'TX-0401', 'currency': 'EUR', 'amount': 180}]}}}
        self.assertFalse(A.tool_result_row_numeric(
            trace, 'get_transactions', 'transactions',
            {'id': 'TX-0401', 'currency': 'EUR'}, 'amount', 240).passed)


if __name__ == '__main__':
    unittest.main()
