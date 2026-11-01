import tempfile
import unittest
from pathlib import Path
from src.task.MaterialNeedsReport import conversion_projection, describe_job, write_needs_report


class TestMaterialNeedsReport(unittest.TestCase):
    def test_reserves_lower_tier_demand_before_conversion(self):
        p = conversion_projection([[14,5],[0,2],[0,1]])
        self.assertEqual([5,3,0],p['after_conversion'])
        self.assertEqual([0,0,1],p['missing'])

    def test_multistep_conversion_can_cover_high_tier_without_drops(self):
        p = conversion_projection([[32,5],[0,0],[0,3]])
        self.assertEqual([0,0,0],p['missing'])
        self.assertEqual([5,0,3],p['after_conversion'])

    def test_mixed_or_unknown_family_not_blindly_converted(self):
        j={'target':'穗穗','kind':'武器/技能','repeat':0,'material_counts':[[200,5],[200,5],[40,43],[5,67]]}
        self.assertIsNone(describe_job(j)['conversion_estimate'])

    def test_heart_four_tier_surplus_pauses_farming_for_recipe_check(self):
        j = {'target': '心', 'kind': '武器/技能', 'repeat': 0,
             'material_counts': [[329, 25], [417, 28], [79, 55], [8, 67]]}
        projection = describe_job(j)['conversion_estimate']
        self.assertEqual([0, 0, 0, 0], projection['missing'])
        self.assertFalse(describe_job(j)['conversion_verified'])

    def test_report_remains_explicit_about_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            data=write_needs_report({'jobs':[{'target':'弗洛洛','kind':'武器/技能','repeat':0,'material_counts':[[32,5],[0,0],[0,3]]}]},directory=folder)
            self.assertFalse(data['jobs'][0]['conversion_verified'])
            self.assertEqual([0,0,0],data['jobs'][0]['conversion_estimate']['missing'])
            self.assertIn('配方待核验',(Path(folder)/'index.html').read_text())
