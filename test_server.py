import sys
import unittest


def _suite() -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module_name in ("tests.test_server_integration", "tests.test_utilities"):
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    if "discover" in sys.argv:
        return unittest.TestSuite()
    return _suite()


if __name__ == "__main__":
    runner = unittest.TextTestRunner()
    result = runner.run(_suite())
    raise SystemExit(not result.wasSuccessful())
