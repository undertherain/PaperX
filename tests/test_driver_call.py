import unittest

from redelivery_agent import normalize_japan_phone_for_call


class DriverCallTest(unittest.TestCase):
    def test_normalizes_japanese_mobile_numbers(self):
        self.assertEqual(normalize_japan_phone_for_call("09012345678"), "+819012345678")
        self.assertEqual(normalize_japan_phone_for_call("81 90 1234 5678"), "+819012345678")
        self.assertEqual(normalize_japan_phone_for_call("+81-90-1234-5678"), "+819012345678")

    def test_rejects_empty_numbers(self):
        self.assertIsNone(normalize_japan_phone_for_call(""))
        self.assertIsNone(normalize_japan_phone_for_call(None))


if __name__ == "__main__":
    unittest.main()
