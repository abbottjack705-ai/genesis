import unittest


class BTests(unittest.TestCase):
    def test_three(self):
        self.assertIsNotNone(object())

    @unittest.skip("fixture skip")
    def test_four(self):
        raise AssertionError("never runs")
