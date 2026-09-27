import unittest

from src.technological_analysis import (
    blank_spatial_deviation,
    calculate_allowance_stages,
    minimum_allowance,
    setup_error,
    validate_chain,
)


class TechnologicalAnalysisTests(unittest.TestCase):
    def test_stock_spatial_deviation_combines_shift_and_warp(self):
        self.assertAlmostEqual(blank_spatial_deviation(30, 0.5, 80), 50)

    def test_setup_error_is_zero_without_reinstallation(self):
        self.assertEqual(setup_error(300, 400, reset=False), 0)
        self.assertAlmostEqual(setup_error(300, 400), 500)

    def test_allowance_formulas(self):
        self.assertAlmostEqual(minimum_allowance(
            roughness_um=10, defect_layer_um=5, spatial_deviation_um=3,
            setup_error_um=4, kind="rotational"), 40)
        self.assertAlmostEqual(minimum_allowance(
            roughness_um=10, defect_layer_um=5, spatial_deviation_um=3,
            setup_error_um=4, kind="linear"), 22)
        self.assertEqual(minimum_allowance(
            roughness_um=10, defect_layer_um=999, spatial_deviation_um=999,
            setup_error_um=999, finishing_only=True), 20)

    def test_stage_calculation_propagates_residual_spatial_deviation(self):
        result = calculate_allowance_stages([{
            "name": "Черновое точение", "roughness_um": 20,
            "defect_layer_um": 10, "ky": 0.06,
            "basing_error_um": 30, "clamping_error_um": 40,
            "kind": "rotational",
        }], initial_spatial_deviation_um=100)[0]
        self.assertAlmostEqual(result["setup_error_um"], 50)
        self.assertAlmostEqual(result["minimum_allowance_um"], 2 * (20 + 10 + (100**2 + 50**2) ** 0.5))
        self.assertAlmostEqual(result["residual_spatial_deviation_um"], 6)

    def test_chain_tree_checks_technological_dimensions_only(self):
        surfaces = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        links = [
            {"label": "A1", "type": "Технологический размер", "start": "1", "end": "2"},
            {"label": "A2", "type": "Технологический размер", "start": "2", "end": "3"},
            {"label": "K1", "type": "Конструкторский размер", "start": "1", "end": "3"},
        ]
        self.assertEqual(validate_chain(surfaces, links), [])


if __name__ == "__main__":
    unittest.main()
