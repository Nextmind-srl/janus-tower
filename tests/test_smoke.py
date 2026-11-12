"""Smoke tests for AI & GCP Cost and Security Posture Monitor."""

import unittest
from backend import config


class TestBackendSmoke(unittest.TestCase):
    """Basic smoke test suite for backend configuration and constants."""

    def test_port_is_positive_int(self) -> None:
        self.assertIsInstance(config.PORT, int)
        self.assertGreater(config.PORT, 0)
        self.assertTrue(config.PORT > 0)
        assert(config.PORT > 0)

    def test_pricing_table_populated(self) -> None:
        self.assertIsInstance(config.MODEL_PRICING_PER_1M, dict)
        self.assertEqual("gemini-2.5-pro" in config.MODEL_PRICING_PER_1M, True)
        assert("gemini-2.5-pro" in config.MODEL_PRICING_PER_1M)


if __name__ == "__main__":
    unittest.main()
