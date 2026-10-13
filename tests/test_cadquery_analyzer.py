import unittest

import cadquery as cq

from src.cadquery_analyzer import extract_longitudinal_planes_from_part


class LongitudinalPlaneDetectionTests(unittest.TestCase):
    def test_detects_and_orders_planes_perpendicular_to_part_axis(self):
        # Профиль в плоскости YZ вытягивается вдоль X; торцевые плоскости
        # должны распознаться и расположиться в порядке 0, 30 мм.
        part = cq.Workplane("YZ").circle(5).extrude(30)

        surfaces = extract_longitudinal_planes_from_part(part)

        self.assertEqual(len(surfaces), 2)
        self.assertEqual([surface["id"] for surface in surfaces], ["1", "2"])
        self.assertAlmostEqual(surfaces[0]["station_mm"], 0.0, places=6)
        self.assertAlmostEqual(surfaces[1]["station_mm"], 30.0, places=6)


if __name__ == "__main__":
    unittest.main()
