import unittest

from redelivery_agent import (
    build_short_driver_call_objective,
    format_driver_call_outcome,
    normalize_japan_phone_for_call,
    plan_driver_call_from_recognition,
    plan_redelivery_from_recognition,
    summarize_driver_call_outcome,
)
from slip_recognition import SlipRecognition


class DriverCallTest(unittest.TestCase):
    def test_normalizes_japanese_mobile_numbers(self):
        self.assertEqual(normalize_japan_phone_for_call("09012345678"), "+819012345678")
        self.assertEqual(normalize_japan_phone_for_call("81 90 1234 5678"), "+819012345678")
        self.assertEqual(normalize_japan_phone_for_call("+81-90-1234-5678"), "+819012345678")

    def test_rejects_empty_numbers(self):
        self.assertIsNone(normalize_japan_phone_for_call(""))
        self.assertIsNone(normalize_japan_phone_for_call(None))

    def test_driver_objective_is_short_and_handles_rejection(self):
        objective = build_short_driver_call_objective("123456789012")
        self.assertIn("必ず相手の返答を待つ", objective)
        self.assertIn("今日中は可能ですか", objective)
        self.assertIn("123456789012", objective)

    def test_summarizes_too_late_for_today(self):
        outcome = summarize_driver_call_outcome(
            {
                "status": "completed",
                "turns": [
                    {"role": "assistant", "text": "今日中の再配達は可能ですか？"},
                    {"role": "user", "text": "Sorry, too late for today."},
                ],
            }
        )
        self.assertIs(outcome.today_available, False)
        self.assertIn("not available", outcome.summary)
        self.assertIn("tomorrow", outcome.next_step)
        self.assertIn("too late", format_driver_call_outcome(outcome))

    def test_summarizes_japanese_soft_rejection(self):
        outcome = summarize_driver_call_outcome(
            {
                "status": "completed",
                "turns": [
                    {"role": "user", "text": "もしもし。"},
                    {"role": "assistant", "text": "今日中の再配達は可能ですか？"},
                    {"role": "user", "text": "いやあ、すみません。今日はもう終わりだと思います。"},
                    {"role": "assistant", "text": "最短はいつですか？"},
                    {"role": "user", "text": "あ、それはあまり知りませんが、ウェブサイトで調べてください。"},
                ],
            }
        )
        self.assertIs(outcome.today_available, False)
        self.assertIn("not available", outcome.summary)
        self.assertIn("tomorrow", outcome.next_step)

    def test_unclear_outcome_defaults_to_form_fallback(self):
        outcome = summarize_driver_call_outcome(
            {
                "status": "completed",
                "turns": [
                    {"role": "user", "text": "確認します。"},
                    {"role": "assistant", "text": "ありがとうございます。"},
                ],
            }
        )
        self.assertIsNone(outcome.today_available)
        self.assertIn("did not clearly confirm", outcome.summary)
        self.assertIn("tomorrow", outcome.next_step)

    def test_builds_plans_from_cached_recognition(self):
        recognition = SlipRecognition(
            carrier="yamato",
            tracking_number="123456789012",
            phone_number="08011112222",
            confidence=0.9,
            notes="",
        )
        booking = plan_redelivery_from_recognition(recognition, "around six pm")
        self.assertEqual(booking.time_slot, "18:00-20:00")
        self.assertEqual(booking.tracking_number, "123456789012")
        noon_booking = plan_redelivery_from_recognition(recognition, "around noon")
        self.assertEqual(noon_booking.time_slot, "午前中")

        call = plan_driver_call_from_recognition(recognition)
        self.assertEqual(call.driver_phone_number, "+818011112222")
        self.assertIn("123456789012", call.objective)


if __name__ == "__main__":
    unittest.main()
