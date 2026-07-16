from django.test import SimpleTestCase

from apps.analytics.mineral_heatmap import (
    _concentration_contours,
    _decay_sites,
    _sum_pairwise_products,
)


class MineralHeatmapMathTests(SimpleTestCase):
    def test_structure_intersection_has_tighter_decay(self):
        lats = [-0.02, -0.01, 0.0, 0.01, 0.02]
        lngs = [-0.02, -0.01, 0.0, 0.01, 0.02]
        raw = [[0.0] * 5 for _ in range(5)]
        raw[2][2] = 1.0

        broad = _decay_sites(
            raw,
            [[False] * 5 for _ in range(5)],
            lats,
            lngs,
            preserve_background=False,
        )
        tight_structure = _decay_sites(
            raw,
            [[i == 2 and j == 2 for j in range(5)] for i in range(5)],
            lats,
            lngs,
            preserve_background=False,
        )

        self.assertAlmostEqual(broad[2][2], tight_structure[2][2], places=6)
        self.assertLess(tight_structure[2][3], broad[2][3])

    def test_multi_mineral_strength_sums_pairwise_products(self):
        self.assertEqual(_sum_pairwise_products([4.0, 4.0]), 16.0)
        self.assertEqual(_sum_pairwise_products([8.0, 9.0]), 72.0)
        self.assertEqual(_sum_pairwise_products([4.0, 4.0, 2.0]), 32.0)

    def test_cutoff_is_mean_plus_two_population_standard_deviations(self):
        grid = [[1.0] * 10 for _ in range(10)]
        for i in range(4, 6):
            for j in range(4, 7):
                grid[i][j] = 10.0
        lats = [float(i) * 0.01 for i in range(10)]
        lngs = [float(j) * 0.01 for j in range(10)]

        stats, contours = _concentration_contours(grid, lats, lngs)

        self.assertAlmostEqual(
            stats["cutoff"],
            stats["mean"] + (2.0 * stats["stdev"]),
            places=3,
        )
        self.assertGreater(stats["cutoff"], stats["mean"])
        self.assertTrue(
            any(
                contour["level"] == "anomaly" and contour.get("coordinates")
                for contour in contours
            )
        )
