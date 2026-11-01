import unittest
from src.task.SharedMaterialInventory import summarize_shared_inventory


class TestSharedMaterialInventory(unittest.TestCase):
    def test_shared_stock_counted_once_with_combined_demand(self):
        rows = [{'target': 'A', 'item_name': 'x', 'required': 8, 'inventory': 10},
                {'target': 'B', 'item_name': 'x', 'required': 7, 'inventory': 10}]
        result = summarize_shared_inventory(rows)[0]
        self.assertEqual(15, result['required_total'])
        self.assertEqual(10, result['inventory'])
        self.assertEqual(5, result['missing_after_synthesis'])

    def test_synthesis_preserves_other_roles_lower_tier_demand(self):
        rows = [{'target': 'A', 'item_name': 'low', 'required': 4, 'inventory': 20},
                {'target': 'B', 'item_name': 'low', 'required': 4, 'inventory': 20},
                {'target': 'A', 'item_name': 'high', 'required': 5, 'inventory': 0}]
        result = {r['item_name']: r for r in summarize_shared_inventory(rows, [('low','high',3)])}
        self.assertEqual(4, result['high']['craft_output'])
        self.assertEqual(1, result['high']['missing_after_synthesis'])
        self.assertEqual(8, result['low']['projected_inventory'])

    def test_only_craft_needed_quantity(self):
        rows = [{'target': 'A', 'item_name': 'low', 'required': 1, 'inventory': 100},
                {'target': 'A', 'item_name': 'high', 'required': 2, 'inventory': 1}]
        result = {r['item_name']: r for r in summarize_shared_inventory(rows, [('low','high',3)])}
        self.assertEqual(1, result['high']['craft_output'])
        self.assertEqual(97, result['low']['projected_inventory'])

    def test_conflicting_global_counts_are_not_added_or_guessed(self):
        rows = [{'target': 'A', 'item_name': 'x', 'required': 8, 'inventory': 10},
                {'target': 'B', 'item_name': 'x', 'required': 7, 'inventory': 12}]
        result = summarize_shared_inventory(rows)[0]
        self.assertTrue(result['inventory_conflict'])
        self.assertIsNone(result['missing_after_synthesis'])
