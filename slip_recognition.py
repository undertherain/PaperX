import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Any


SLIP_RECOGNITION_PROMPT = """You are reading a Japanese parcel redelivery slip photo.
Extract only fields needed to book redelivery. Return ONLY JSON with this schema:
{
  "carrier": "yamato" | "sagawa" | "japan_post" | "unknown",
  "tracking_number": string | null,
  "phone_number": string | null,
  "confidence": number,
  "notes": string
}

Rules:
- tracking_number is the parcel waybill / inquiry number: 伝票番号, お問い合わせ番号, or送り状番号.
- Return tracking_number as digits only, no hyphens or spaces.
- Return phone_number as digits only, no hyphens or spaces. If no phone number is visible, use null.
- Do not invent numbers. If a digit is unclear, set the field to null and explain briefly in notes.
- confidence should be 0.0 to 1.0 for the extracted fields overall."""

TRACKING_RETRY_PROMPT = """Look at the same Japanese parcel redelivery slip again.
Focus only on finding the parcel tracking / waybill number.
Return ONLY JSON with this schema:
{
  "carrier": "yamato" | "sagawa" | "japan_post" | "unknown",
  "tracking_number": string | null,
  "phone_number": string | null,
  "confidence": number,
  "notes": string
}

Rules:
- tracking_number is the parcel waybill / inquiry number: 伝票番号, お問い合わせ番号, or送り状番号.
- For Yamato/Kuroneko slips, the tracking number is usually 11 or 12 digits.
- Ignore numbers labeled 携帯番号, 電話番号, TEL, postal codes, dates, and prices.
- Return digits only, no hyphens or spaces.
- If some digits are grouped or spaced visually, join them.
- Do not invent numbers. If the waybill area is unreadable, return null and explain why."""


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
DEFAULT_PHONE_NUMBER = "09012345678"


@dataclass(frozen=True)
class SlipRecognition:
    carrier: str
    tracking_number: str | None
    phone_number: str | None
    confidence: float
    notes: str

    @property
    def booking_phone_number(self) -> str:
        return self.phone_number or DEFAULT_PHONE_NUMBER

    def to_dict(self) -> dict[str, Any]:
        return {
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "phone_number": self.phone_number,
            "confidence": self.confidence,
            "notes": self.notes,
        }


def encode_image(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def digits_only(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def normalize_recognition(payload: dict[str, Any]) -> SlipRecognition:
    carrier = str(payload.get("carrier") or "unknown").strip().lower()
    if carrier not in {"yamato", "sagawa", "japan_post", "unknown"}:
        carrier = "unknown"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return SlipRecognition(
        carrier=carrier,
        tracking_number=digits_only(payload.get("tracking_number")),
        phone_number=digits_only(payload.get("phone_number")),
        confidence=confidence,
        notes=str(payload.get("notes") or "").strip(),
    )


def recognize_slip(image_path: str, model: str = DEFAULT_MODEL, attempts: int = 3) -> SlipRecognition:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY to enable slip recognition.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai package to enable slip recognition.") from exc

    client = OpenAI()
    image_url = encode_image(image_path)
    prompts = [SLIP_RECOGNITION_PROMPT] + [TRACKING_RETRY_PROMPT] * max(0, attempts - 1)
    results: list[SlipRecognition] = []

    for prompt in prompts:
        result = _recognize_slip_once(client, image_url, prompt, model)
        results.append(result)
        if result.tracking_number:
            return merge_recognition_results(results)

    return merge_recognition_results(results)


def _recognize_slip_once(client: Any, image_url: str, prompt: str, model: str) -> SlipRecognition:
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    )
    content = response.choices[0].message.content or "{}"
    return normalize_recognition(json.loads(content))


def merge_recognition_results(results: list[SlipRecognition]) -> SlipRecognition:
    if not results:
        return SlipRecognition(
            carrier="unknown",
            tracking_number=None,
            phone_number=None,
            confidence=0.0,
            notes="No recognition attempts were run.",
        )

    tracking_source = next((result for result in results if result.tracking_number), None)
    phone_source = next((result for result in results if result.phone_number), None)
    carrier_source = next((result for result in results if result.carrier != "unknown"), results[0])
    best_confidence = max(result.confidence for result in results)
    notes = " | ".join(
        f"attempt {index}: {result.notes or 'no notes'}"
        for index, result in enumerate(results, start=1)
        if result.notes
    )

    return SlipRecognition(
        carrier=carrier_source.carrier,
        tracking_number=tracking_source.tracking_number if tracking_source else None,
        phone_number=phone_source.phone_number if phone_source else None,
        confidence=best_confidence,
        notes=notes or results[-1].notes,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract redelivery booking fields from a slip photo.")
    parser.add_argument("image", help="path to a redelivery slip photo")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    result = recognize_slip(args.image, model=args.model)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
