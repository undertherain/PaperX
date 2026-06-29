import re
import unicodedata
import json
import os
from typing import Any


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

WORD_HOURS = {
    "two": "14",
    "four": "16",
    "six": "18",
    "seven": "19",
    "十四": "14",
    "十六": "16",
    "十八": "18",
    "十九": "19",
}

TIME_SLOT_MATCH_PROMPT = """Map the user's requested parcel redelivery time to one available slot.
Return ONLY JSON with this schema:
{"slot": string | null, "confidence": number, "reason": string}

Available slots:
- 午前中
- 14:00-16:00
- 16:00-18:00
- 18:00-20:00
- 19:00-21:00

Rules:
- Choose exactly one available slot when the user intent is clear.
- Interpret casual English or Japanese phrases, e.g. "around six pm", "after work", "morning", "夕方".
- If the request is ambiguous or conflicts with the available slots, use null.
- Do not invent slots."""


def _compact_time_text(text: str) -> str:
    compact = unicodedata.normalize("NFKC", text).strip().lower()
    compact = re.sub(r"\s+", "", compact)
    compact = compact.replace("~", "-").replace("〜", "-").replace("～", "-")
    compact = compact.replace("から", "-").replace("to", "-")
    compact = compact.replace("時半", ":30").replace("時", ":00")
    for word, hour in WORD_HOURS.items():
        compact = compact.replace(word, hour)
    return compact


def _local_time_slot(text: str) -> str | None:
    compact = _compact_time_text(text)

    if any(token in compact for token in ("asap", "earliest", "早め", "一番早")):
        return "午前中"
    if any(token in compact for token in ("afterwork", "仕事後", "退勤後")):
        return "19:00-21:00"

    around_match = re.search(r"(around|about|approx|approximately|頃|くらい|ぐらい)?(14|16|18|19|2pm|4pm|6pm|7pm|7)", compact)
    if around_match:
        return _slot_for_hour(around_match.group(2))

    return None


def _slot_for_hour(hour: str) -> str | None:
    if hour in {"14", "2pm"}:
        return "14:00-16:00"
    if hour in {"16", "4pm"}:
        return "16:00-18:00"
    if hour in {"18", "6pm"}:
        return "18:00-20:00"
    if hour in {"19", "7pm", "7"}:
        return "19:00-21:00"
    return None


def _json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def ai_time_slot(text: str) -> str | None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-5.5")
    try:
        response = OpenAI().chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": TIME_SLOT_MATCH_PROMPT},
                {"role": "user", "content": text},
            ],
        )
    except Exception:
        return None

    payload = _json_object(response.choices[0].message.content or "{}")
    slot = payload.get("slot")
    if slot in VALID_TIME_SLOTS:
        return slot
    return None


def canonical_time_slot(text: str) -> str | None:
    compact = _compact_time_text(text)

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
        return _local_time_slot(text) or ai_time_slot(text)

    return _slot_for_hour(hour_match.group(1)) or _local_time_slot(text) or ai_time_slot(text)


def normalize_time_slot(text: str) -> str:
    return canonical_time_slot(text) or text.strip()
