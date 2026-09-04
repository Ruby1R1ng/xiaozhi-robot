"""Compatibility smoke entry point for the synchronous-result failover pipeline."""
import unittest
from test_resilient_search import Tests

result = unittest.TextTestRunner().run(unittest.TestSuite([Tests("test_failovers")]))
if not result.wasSuccessful():
    raise SystemExit(1)
