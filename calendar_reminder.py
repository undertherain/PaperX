import argparse
import json
import os
import time
from datetime import date, datetime, time as day_time, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from time_slots import VALID_TIME_SLOTS, normalize_time_slot


DEFAULT_CALENDAR_PATH = Path("fake_calendar_app/reminders.json")

SLOT_TIMES = {
    "午前中": ("08:00", "12:00"),
    "14:00-16:00": ("14:00", "16:00"),
    "16:00-18:00": ("16:00", "18:00"),
    "18:00-20:00": ("18:00", "20:00"),
    "19:00-21:00": ("19:00", "21:00"),
}


def redelivery_date(days_from_today: int = 1, today: date | None = None) -> date:
    base = today or date.today()
    return base + timedelta(days=days_from_today)


def _parse_clock(value: str) -> day_time:
    hour, minute = value.split(":", maxsplit=1)
    return day_time(hour=int(hour), minute=int(minute))


def slot_window(delivery_date: date, time_slot: str) -> tuple[datetime, datetime]:
    slot = normalize_time_slot(time_slot)
    if slot not in VALID_TIME_SLOTS:
        valid = ", ".join(VALID_TIME_SLOTS)
        raise ValueError(f"Unsupported time slot '{time_slot}'. Use one of: {valid}")

    start_text, end_text = SLOT_TIMES[slot]
    return (
        datetime.combine(delivery_date, _parse_clock(start_text)),
        datetime.combine(delivery_date, _parse_clock(end_text)),
    )


def _load_reminders(calendar_path: Path) -> list[dict[str, Any]]:
    if not calendar_path.exists():
        return []
    try:
        payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def create_redelivery_reminder(
    tracking_number: str,
    phone_number: str,
    time_slot: str,
    delivery_date: date | None = None,
    calendar_path: Path | str = DEFAULT_CALENDAR_PATH,
) -> dict[str, Any]:
    calendar_file = Path(calendar_path)
    delivery_day = delivery_date or redelivery_date()
    slot = normalize_time_slot(time_slot)
    starts_at, ends_at = slot_window(delivery_day, slot)
    reminder_at = starts_at - timedelta(hours=1)

    reminder = {
        "id": f"redelivery-{int(time.time() * 1000)}",
        "title": "Parcel redelivery",
        "tracking_number": tracking_number,
        "phone_number": phone_number,
        "delivery_date": delivery_day.isoformat(),
        "time_slot": slot,
        "starts_at": starts_at.isoformat(timespec="minutes"),
        "ends_at": ends_at.isoformat(timespec="minutes"),
        "reminder_at": reminder_at.isoformat(timespec="minutes"),
        "source": "PaperX redelivery skill",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    calendar_file.parent.mkdir(parents=True, exist_ok=True)
    reminders = _load_reminders(calendar_file)
    reminders.append(reminder)
    calendar_file.write_text(
        json.dumps(reminders, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return reminder


def serve_calendar(host: str = "127.0.0.1", port: int = 8765) -> None:
    os.chdir(Path("fake_calendar_app"))
    server = ThreadingHTTPServer((host, port), SimpleHTTPRequestHandler)
    print(f"Fake calendar running at http://{host}:{port}/")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or view fake calendar reminders.")
    parser.add_argument("--serve", action="store_true", help="serve the fake calendar UI")
    parser.add_argument("--tracking", help="tracking number for a redelivery reminder")
    parser.add_argument("--phone", help="phone number for a redelivery reminder")
    parser.add_argument("--time-slot", help="redelivery time slot, e.g. 19:00-21:00")
    parser.add_argument("--date", help="delivery date as YYYY-MM-DD; defaults to tomorrow")
    args = parser.parse_args()

    if args.serve:
        serve_calendar()
        return

    if not (args.tracking and args.phone and args.time_slot):
        parser.error("--tracking, --phone, and --time-slot are required unless --serve is used")

    delivery_day = date.fromisoformat(args.date) if args.date else None
    reminder = create_redelivery_reminder(
        tracking_number=args.tracking,
        phone_number=args.phone,
        time_slot=args.time_slot,
        delivery_date=delivery_day,
    )
    print(json.dumps(reminder, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
