import unittest

from src.operation_planning import (
    build_process_surface_sequence,
    quality_options,
    resize_operation_sequence,
)


class OperationPlanningTests(unittest.TestCase):
    def test_quality_options_match_recommendation_ranges(self):
        self.assertEqual(quality_options("Черновое точение"), [11, 12, 13])
        self.assertEqual(quality_options("Чистовое шлифование"), [5, 6, 7])
        self.assertEqual(quality_options("Заготовка"), [14, 15, 16, 17])

    def test_resizing_preserves_stages_and_clears_incompatible_grade(self):
        result = resize_operation_sequence([
            {"operation": "Черновое точение", "grade": 12},
            {"operation": "Чистовое шлифование", "grade": 12},
        ], 3)
        self.assertEqual(result[0]["grade"], 12)
        self.assertIsNone(result[1]["grade"])
        self.assertIsNone(result[2]["operation"])

    def test_process_sequence_reuses_detected_final_surface(self):
        sequence = build_process_surface_sequence(
            {"key": "diametral:12", "chain_id": "D3"},
            {
                "operation_count": 2,
                "stock_grade": 16,
                "operations": [
                    {"operation": "Черновое точение", "grade": 12},
                    {"operation": "Чистовое точение", "grade": 7},
                ],
            },
        )
        self.assertEqual([item["id"] for item in sequence], ["D3-З", "D3.1", "D3"])
        self.assertEqual([item["kind"] for item in sequence], ["stock", "intermediate", "finished"])
        self.assertTrue(sequence[-1]["is_detected_surface"])

    def test_invalid_operation_count_is_rejected(self):
        with self.assertRaises(ValueError):
            resize_operation_sequence([], 21)


if __name__ == "__main__":
    unittest.main()
