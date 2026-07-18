import unittest

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


if __name__ == "__main__":
    unittest.main()
