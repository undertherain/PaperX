import re
import unicodedata


VALID_TIME_SLOTS = ("午前中", "14:00-16:00", "16:00-18:00", "18:00-20:00", "19:00-21:00")

TIME_SLOT_ALIASES = {
    "morning": "午前中",
    "am": "午前中",
    "午前": "午前中",
    "午前中": "午前中",
    "14-16": "14:00-16:00",
    "14:00-16:00": "14:00-16:00",
    "16-18": "16:00-18:00",
    "16:00-18:00": "16:00-18:00",
    "18-20": "18:00-20:00",
    "18:00-20:00": "18:00-20:00",
    "19-21": "19:00-21:00",
    "19:00-21:00": "19:00-21:00",
    "2-4": "14:00-16:00",
    "2pm-4pm": "14:00-16:00",
    "4-6": "16:00-18:00",
    "4pm-6pm": "16:00-18:00",
    "6-8": "18:00-20:00",
    "6pm-8pm": "18:00-20:00",
    "7-9": "19:00-21:00",
    "7pm-9pm": "19:00-21:00",
    "evening": "19:00-21:00",
    "night": "19:00-21:00",
    "late": "19:00-21:00",
    "夜": "19:00-21:00",
    "夕方": "18:00-20:00",
}


def canonical_time_slot(text: str) -> str | None:
    compact = unicodedata.normalize("NFKC", text).strip().lower()
    compact = re.sub(r"\s+", "", compact)
    compact = compact.replace("~", "-").replace("〜", "-").replace("～", "-")
    compact = compact.replace("から", "-").replace("to", "-")
    compact = compact.replace("時", ":00").replace("時半", ":30")

    if compact in TIME_SLOT_ALIASES:
        return TIME_SLOT_ALIASES[compact]
    if compact in VALID_TIME_SLOTS:
        return compact

    range_match = re.search(
        r"(?<!\d)(午前中|1?4(?::00)?-1?6(?::00)?|1?6(?::00)?-1?8(?::00)?|1?8(?::00)?-20(?::00)?|1?9(?::00)?-21(?::00)?|2(?:pm)?-4(?:pm)?|4(?:pm)?-6(?:pm)?|6(?:pm)?-8(?:pm)?|7(?:pm)?-9(?:pm)?)(?!\d)",
        compact,
    )
    if range_match:
        return TIME_SLOT_ALIASES.get(range_match.group(1), range_match.group(1))

    hour_match = re.search(r"(?<!\d)(14|16|18|19|2pm|4pm|6pm|7pm|7)(?!\d)", compact)
    if not hour_match:
        return None

    hour = hour_match.group(1)
    if hour in {"14", "2pm"}:
        return "14:00-16:00"
    if hour in {"16", "4pm"}:
        return "16:00-18:00"
    if hour in {"18", "6pm"}:
        return "18:00-20:00"
    if hour in {"19", "7pm", "7"}:
        return "19:00-21:00"
    return None


def normalize_time_slot(text: str) -> str:
    return canonical_time_slot(text) or text.strip()
