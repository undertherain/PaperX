import unittest

from time_slots import normalize_time_slot


class TimeSlotNormalizationTest(unittest.TestCase):
    def test_normalizes_natural_language_time(self):
        self.assertEqual(normalize_time_slot("around six pm"), "18:00-20:00")
        self.assertEqual(normalize_time_slot("six pm"), "18:00-20:00")
        self.assertEqual(normalize_time_slot("after work"), "19:00-21:00")

    def test_keeps_existing_slot_forms(self):
        self.assertEqual(normalize_time_slot("19:00-21:00"), "19:00-21:00")
        self.assertEqual(normalize_time_slot("4pm-6pm"), "16:00-18:00")
        self.assertEqual(normalize_time_slot("morning"), "午前中")

    def test_unmatched_text_passes_through(self):
        self.assertEqual(normalize_time_slot("sometime convenient"), "sometime convenient")


if __name__ == "__main__":
    unittest.main()
