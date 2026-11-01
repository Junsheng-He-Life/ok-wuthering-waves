import unittest
from src.task.MaterialQueueSnapshot import build_queue_snapshot


class TestMaterialQueueSnapshot(unittest.TestCase):
    def job(self, target='折枝', kind='武器/技能', counts=None, **extra):
        return {'target': target, 'kind': kind, 'repeat': 0,
                'material_counts': [[2, 10]] if counts is None else counts, **extra}

    def test_new_party_displays_without_personal_audit(self):
        names = ['今汐', '折枝', '维里奈']
        snapshot = build_queue_snapshot({'targets': names,
                                        'jobs': [self.job(name) for name in names]})
        self.assertEqual(names, list(snapshot['roles']))
        self.assertEqual(8, snapshot['roles']['折枝'][0]['stock']['missing'])
        self.assertEqual('材料名称待核对', snapshot['roles']['折枝'][0]['item_name'])

    def test_legacy_progress_derives_targets_only_from_current_jobs(self):
        snapshot = build_queue_snapshot({'jobs': [self.job('达妮娅'), self.job('千咲')]})
        self.assertEqual(['达妮娅', '千咲'], list(snapshot['roles']))

    def test_explicit_targets_exclude_stale_other_party_jobs(self):
        snapshot = build_queue_snapshot({'targets': ['折枝'],
                                        'jobs': [self.job('折枝'), self.job('心')]})
        self.assertEqual(['折枝'], list(snapshot['roles']))

    def test_old_completed_flags_cannot_cover_observed_shortage(self):
        snapshot = build_queue_snapshot({'jobs': [self.job(satisfied=True,
            completion_reason='用户确认完成', shared_materials=[{'missing_after_synthesis': 0}])],
            'completed_jobs': [0]}, {'items': [{'target': '折枝', 'item_name': '旧材料',
                'completed': True, 'inventory': 999, 'required': 0}]})
        row = snapshot['roles']['折枝'][0]
        self.assertEqual(2, row['stock']['inventory'])
        self.assertEqual(10, row['required'])
        self.assertEqual(8, row['stock']['missing'])

    def test_exact_audit_identity_only_supplies_name(self):
        audit = {'items': [{'target': '折枝', 'resource_kind': '武器/技能', 'repeat': 0,
                            'tier_from_end': 1, 'item_name': '已核对材料名',
                            'inventory': 999, 'required': 0, 'completed': True}]}
        row = build_queue_snapshot({'jobs': [self.job()]}, audit)['roles']['折枝'][0]
        self.assertEqual('已核对材料名', row['item_name'])
        self.assertEqual(8, row['stock']['missing'])

    def test_missing_or_ambiguous_audit_row_identity_uses_text_fallback(self):
        for items in ([{'target': '折枝', 'item_name': '无行号'}],
                      [{'target': '折枝', 'resource_kind': '武器/技能', 'repeat': 0,
                        'tier_from_end': 1, 'item_name': name} for name in ['甲', '乙']]):
            with self.subTest(items=items):
                row = build_queue_snapshot({'jobs': [self.job()]}, {'items': items})['roles']['折枝'][0]
                self.assertEqual('材料名称待核对', row['item_name'])

    def test_missing_or_invalid_counts_remain_unknown_even_when_satisfied(self):
        for counts in ([], [[-1, 4]], [['2', 4]], [[False, 4]]):
            with self.subTest(counts=counts):
                row = build_queue_snapshot({'jobs': [self.job(counts=counts, satisfied=True)]})['roles']['折枝'][0]
                self.assertIsNone(row['stock']['missing'])
                self.assertTrue(row['stock']['needs_verification'])

    def test_unscanned_target_is_visible_as_unknown(self):
        snapshot = build_queue_snapshot({'targets': ['折枝'], 'jobs': []})
        self.assertTrue(snapshot['roles']['折枝'][0]['stock']['needs_verification'])

    def test_sufficient_observed_counts_remove_only_that_shortage(self):
        snapshot = build_queue_snapshot({'jobs': [self.job(counts=[[10, 2], [1, 4]])]})
        self.assertEqual(1, len(snapshot['roles']['折枝']))
        self.assertEqual(3, snapshot['roles']['折枝'][0]['stock']['missing'])

    def test_missing_experience_rows_do_not_imply_completion(self):
        snapshot = build_queue_snapshot({'jobs': [self.job()]})
        self.assertIn('不推断已完成', snapshot['resource_status'])
        snapshot = build_queue_snapshot({'jobs': [self.job(kind='贝币', counts=[[10, 2]])]})
        self.assertIn('已记录', snapshot['resource_status'])

    def test_snapshot_time_comes_from_progress_not_audit_or_ledger(self):
        snapshot = build_queue_snapshot({'jobs': [self.job()], 'observed_at': '2026-10-27'},
                                        {'observed_at': '2026-10-28', 'items': []})
        self.assertEqual('2026-10-27', snapshot['observed_at'])
        self.assertEqual({}, build_queue_snapshot({})['roles'])


if __name__ == '__main__':
    unittest.main()
