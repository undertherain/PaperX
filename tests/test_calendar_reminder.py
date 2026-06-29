import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from calendar_reminder import create_redelivery_reminder, redelivery_date, slot_window


class CalendarReminderTest(unittest.TestCase):
    def test_redelivery_date_defaults_to_next_day(self):
        self.assertEqual(redelivery_date(today=date(2026, 6, 29)), date(2026, 6, 30))

    def test_slot_window_maps_time_slot_to_datetimes(self):
        starts_at, ends_at = slot_window(date(2026, 6, 30), "19:00-21:00")

        self.assertEqual(starts_at.isoformat(timespec="minutes"), "2026-06-30T19:00")
        self.assertEqual(ends_at.isoformat(timespec="minutes"), "2026-06-30T21:00")

    def test_create_redelivery_reminder_writes_calendar_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            calendar_path = Path(tmpdir) / "reminders.json"
            reminder = create_redelivery_reminder(
                tracking_number="123456789012",
                phone_number="09012345678",
                time_slot="after work",
                delivery_date=date(2026, 6, 30),
                calendar_path=calendar_path,
            )

            reminders = json.loads(calendar_path.read_text(encoding="utf-8"))

        self.assertEqual(reminder["time_slot"], "19:00-21:00")
        self.assertEqual(reminders[0]["starts_at"], "2026-06-30T19:00")
        self.assertEqual(reminders[0]["reminder_at"], "2026-06-30T18:00")


if __name__ == "__main__":
    unittest.main()
