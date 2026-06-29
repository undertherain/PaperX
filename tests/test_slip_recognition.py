import unittest

from slip_recognition import SlipRecognition, merge_recognition_results


class SlipRecognitionTest(unittest.TestCase):
    def test_merge_uses_later_tracking_number(self):
        merged = merge_recognition_results(
            [
                SlipRecognition(
                    carrier="yamato",
                    tracking_number=None,
                    phone_number="08011112222",
                    confidence=0.4,
                    notes="tracking area unclear",
                ),
                SlipRecognition(
                    carrier="yamato",
                    tracking_number="314159265358",
                    phone_number=None,
                    confidence=0.8,
                    notes="tracking found",
                ),
            ]
        )

        self.assertEqual(merged.carrier, "yamato")
        self.assertEqual(merged.tracking_number, "314159265358")
        self.assertEqual(merged.phone_number, "08011112222")
        self.assertEqual(merged.confidence, 0.8)
        self.assertIn("attempt 1", merged.notes)
        self.assertIn("attempt 2", merged.notes)


if __name__ == "__main__":
    unittest.main()
