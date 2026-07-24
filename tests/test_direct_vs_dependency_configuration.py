import unittest

import config
from rolling_solver import configuration_features


class ConfigurationTest(unittest.TestCase):
    def test_full_direct_and_full_only_differ_by_propagation(self):
        direct = configuration_features("full_direct")
        dependency = configuration_features("full")
        self.assertFalse(direct["dependency_propagation"])
        self.assertTrue(dependency["dependency_propagation"])
        direct_without_switch = {k: v for k, v in direct.items() if k != "dependency_propagation"}
        dependency_without_switch = {k: v for k, v in dependency.items() if k != "dependency_propagation"}
        self.assertEqual(direct_without_switch, dependency_without_switch)

    def test_quality_polish_is_uniformly_disabled_for_tuning(self):
        self.assertFalse(config.QUALITY_POLISH_ENABLED)
        self.assertFalse(configuration_features("full_direct")["quality_polish"])
        self.assertFalse(configuration_features("full")["quality_polish"])

    def test_bottleneck_configuration_only_replaces_repair_controller(self):
        direct = configuration_features("full_direct")
        bottleneck = configuration_features("full_bottleneck")
        self.assertTrue(direct["progressive_repair"])
        self.assertTrue(bottleneck["progressive_repair"])
        self.assertFalse(direct["bottleneck_repair"])
        self.assertTrue(bottleneck["bottleneck_repair"])
        self.assertFalse(direct["adaptive_global_bypass"])
        self.assertTrue(bottleneck["adaptive_global_bypass"])
        for feature in (
            "mip_start",
            "impact_region",
            "dependency_propagation",
            "quality_polish",
        ):
            self.assertEqual(direct[feature], bottleneck[feature])


if __name__ == "__main__":
    unittest.main()
