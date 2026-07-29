import unittest
from pathlib import Path

import config
from scripts.prepare_synthetic_forecast_formal_panel import (
    load_forecast_panel,
    profile_map,
    relative_bundle_path,
)


class SyntheticForecastFormalPanelTests(unittest.TestCase):
    def test_frozen_panel_has_seven_missing_profiles(self):
        _, panel = load_forecast_panel(
            Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
        )
        self.assertEqual(len(panel["profiles_to_generate"]), 7)
        self.assertEqual(panel["missing_bundle_count"], 70)
        self.assertEqual(panel["bundle_count"], 80)
        self.assertEqual(
            set(panel["profiles_to_generate"]),
            set(profile_map(panel)) - {"error_010_mixed"},
        )

    def test_every_profile_uses_supported_forecast_mode(self):
        _, panel = load_forecast_panel(
            Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
        )
        for row in profile_map(panel).values():
            self.assertIn(row["forecast_error_mode"], config.FORECAST_ERROR_MODES)
            self.assertGreaterEqual(row["forecast_error"], 0)

    def test_relative_bundle_path_is_portable(self):
        index_dir = Path("root/panel")
        bundle = Path("root/source/example.instance.json")
        relative = relative_bundle_path(index_dir, bundle)
        self.assertEqual(relative, "../source/example.instance.json")


if __name__ == "__main__":
    unittest.main()
