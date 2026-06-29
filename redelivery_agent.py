import argparse
import asyncio
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from slip_recognition import DEFAULT_PHONE_NUMBER, SlipRecognition, recognize_slip
from time_slots import VALID_TIME_SLOTS, normalize_time_slot

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except ImportError:
    pass

DEFAULT_AGENT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
VOICE_AGENT_SERVER_URL = (
    os.getenv("VOICE_AGENT_SERVER_URL")
    or os.getenv("PUBLIC_BASE_URL")
    or "http://127.0.0.1:8080"
)

try:
    from agents import Agent, Runner, function_tool
except ImportError:
    Agent = None
    Runner = None

    def function_tool(func):
        return func


ProgressCallback = Callable[[str], Awaitable[None]]


class RedeliveryPlan(BaseModel):
    carrier: str = Field(description="Detected delivery carrier.")
    tracking_number: str | None = Field(description="Parcel tracking or waybill number, digits only.")
    phone_number: str | None = Field(description="Phone number to use for booking, digits only.")
    requested_time: str = Field(description="Original user time request.")
    time_slot: str = Field(description="Canonical available redelivery slot.")
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    user_summary: str = Field(description="Short confirmation message for the Telegram user.")


class BookingResult(BaseModel):
    success: bool
    time_slot: str
    stdout: str = ""
    stderr: str = ""
    user_summary: str


class DriverCallPlan(BaseModel):
    carrier: str = Field(description="Detected delivery carrier.")
    tracking_number: str | None = Field(description="Parcel tracking or waybill number, digits only.")
    driver_phone_number: str | None = Field(description="Driver or depot phone number to call.")
    objective: str = Field(description="Japanese objective for the voice agent call.")
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    user_summary: str = Field(description="Short confirmation message for the Telegram user.")


class DriverCallResult(BaseModel):
    success: bool
    call_sid: str | None = None
    status: str = ""
    phone_number: str
    objective: str
    error: str = ""
    user_summary: str


class DriverCallOutcome(BaseModel):
    status: str
    today_available: bool | None
    summary: str
    next_step: str
    transcript: str = ""


def _require_agents_sdk() -> None:
    if Agent is None or Runner is None:
        raise RuntimeError("Install the OpenAI Agents SDK: python3 -m pip install openai-agents")


def _recognition_payload(result: SlipRecognition) -> dict[str, Any]:
    return {
        **result.to_dict(),
        "booking_phone_number": result.booking_phone_number,
    }


@function_tool
def read_redelivery_slip(image_path: str) -> dict[str, Any]:
    """Read a redelivery slip image and return the booking fields."""
    return _recognition_payload(recognize_slip(image_path))


@function_tool
def match_requested_time(requested_time: str) -> dict[str, Any]:
    """Map a natural-language time request to one of the supported redelivery slots."""
    time_slot = normalize_time_slot(requested_time)
    return {
        "requested_time": requested_time,
        "time_slot": time_slot if time_slot in VALID_TIME_SLOTS else None,
        "available_slots": list(VALID_TIME_SLOTS),
    }


@function_tool
def book_redelivery_slot(tracking_number: str, phone_number: str, time_slot: str) -> dict[str, Any]:
    """Run the Playwright booking automation for a confirmed redelivery plan."""
    result = subprocess.run(
        [
            sys.executable,
            "tools/playwright_booking.py",
            tracking_number,
            phone_number,
            time_slot,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "success": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@function_tool
def start_driver_call(phone_number: str, objective: str) -> dict[str, Any]:
    """Start an outbound voice-agent call through the OneStop Twilio bridge."""
    normalized_phone = normalize_japan_phone_for_call(phone_number)
    if not normalized_phone:
        return {
            "success": False,
            "phone_number": phone_number,
            "objective": objective,
            "error": "Phone number is missing or invalid.",
        }

    payload = {
        "to": normalized_phone,
        "objective": objective,
    }
    request = urllib.request.Request(
        f"{VOICE_AGENT_SERVER_URL.rstrip('/')}/calls",
        data=json_bytes(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "phone_number": normalized_phone,
            "objective": objective,
            "error": exc.read().decode("utf-8"),
        }
    except OSError as exc:
        return {
            "success": False,
            "phone_number": normalized_phone,
            "objective": objective,
            "error": str(exc),
        }

    try:
        response_payload = json_loads(data)
    except ValueError:
        response_payload = {}
    return {
        "success": bool(response_payload.get("call_sid")),
        "call_sid": response_payload.get("call_sid"),
        "status": response_payload.get("status", ""),
        "phone_number": normalized_phone,
        "objective": objective,
        "error": "",
    }


def build_planning_agent():
    _require_agents_sdk()
    return Agent(
        name="Redelivery planning agent",
        instructions=(
            "You help book Japanese parcel redelivery. Use the tools to read the slip "
            "and map the user's requested time to the available slot list. Do not book "
            "anything in this planning step. If no tracking number or no supported time "
            "slot is found, explain the issue in notes and still return the best structured "
            "plan you can. Keep user_summary short and suitable for Telegram confirmation."
        ),
        tools=[read_redelivery_slip, match_requested_time],
        output_type=RedeliveryPlan,
        model=DEFAULT_AGENT_MODEL,
    )


def build_booking_agent():
    _require_agents_sdk()
    return Agent(
        name="Confirmed redelivery booking agent",
        instructions=(
            "The user has confirmed this redelivery booking. Call the booking tool exactly "
            "once with the confirmed tracking number, phone number, and canonical time slot. "
            "Return whether the automation succeeded and a short Telegram-ready summary."
        ),
        tools=[book_redelivery_slot],
        output_type=BookingResult,
        model=DEFAULT_AGENT_MODEL,
    )


def build_driver_call_planning_agent():
    _require_agents_sdk()
    return Agent(
        name="Driver call planning agent",
        instructions=(
            "You help arrange same-day Japanese parcel redelivery by phone. Use the slip "
            "reader tool. Treat the extracted phone_number as the driver or depot phone "
            "number when it is present. Never use booking_phone_number for calls because "
            "it may be an app fallback, not a driver number. Build a concise Japanese phone-call objective "
            "asking whether redelivery today is possible, preferably this evening, and "
            "include the tracking number. Do not start the call in this planning step. "
            "If no callable phone number is visible, set driver_phone_number to null and "
            "explain that the user should set DRIVER_PHONE_NUMBER or provide a number."
        ),
        tools=[read_redelivery_slip],
        output_type=DriverCallPlan,
        model=DEFAULT_AGENT_MODEL,
    )


def build_driver_call_agent():
    _require_agents_sdk()
    return Agent(
        name="Confirmed driver call agent",
        instructions=(
            "The user confirmed placing a same-day redelivery phone call. Call the tool "
            "exactly once with the confirmed driver phone number and Japanese objective. "
            "Return the call SID, status, and a short Telegram-ready summary."
        ),
        tools=[start_driver_call],
        output_type=DriverCallResult,
        model=DEFAULT_AGENT_MODEL,
    )


def _coerce_plan(value: Any) -> RedeliveryPlan:
    if isinstance(value, RedeliveryPlan):
        return value
    if isinstance(value, str):
        return RedeliveryPlan.model_validate_json(value)
    return RedeliveryPlan.model_validate(value)


def _coerce_booking_result(value: Any) -> BookingResult:
    if isinstance(value, BookingResult):
        return value
    if isinstance(value, str):
        return BookingResult.model_validate_json(value)
    return BookingResult.model_validate(value)


def _coerce_call_plan(value: Any) -> DriverCallPlan:
    if isinstance(value, DriverCallPlan):
        return value
    if isinstance(value, str):
        return DriverCallPlan.model_validate_json(value)
    return DriverCallPlan.model_validate(value)


def _coerce_call_result(value: Any) -> DriverCallResult:
    if isinstance(value, DriverCallResult):
        return value
    if isinstance(value, str):
        return DriverCallResult.model_validate_json(value)
    return DriverCallResult.model_validate(value)


async def plan_redelivery(
    image_path: str,
    requested_time: str,
    progress: ProgressCallback | None = None,
) -> RedeliveryPlan:
    if progress:
        await progress("Agent is reading the slip and matching your requested time...")

    agent = build_planning_agent()
    result = await Runner.run(
        agent,
        input=(
            f"Slip image path: {image_path}\n"
            f"User requested time: {requested_time}\n"
            f"Available slots: {', '.join(VALID_TIME_SLOTS)}"
        ),
    )
    plan = _coerce_plan(result.final_output)

    if not plan.tracking_number:
        raise RuntimeError(f"Agent could not read the tracking number. Notes: {plan.notes or 'none'}")
    if plan.time_slot not in VALID_TIME_SLOTS:
        valid = ", ".join(VALID_TIME_SLOTS)
        raise RuntimeError(f"Agent could not match '{requested_time}' to a supported slot. Use one of: {valid}")

    if progress:
        await progress(f"Agent matched '{requested_time}' to {plan.time_slot}.")
    return plan


def plan_redelivery_from_recognition(
    recognition: SlipRecognition,
    requested_time: str,
) -> RedeliveryPlan:
    if not recognition.tracking_number:
        raise RuntimeError(f"Could not read the tracking number. Notes: {recognition.notes or 'none'}")

    time_slot = normalize_time_slot(requested_time)
    if time_slot not in VALID_TIME_SLOTS:
        valid = ", ".join(VALID_TIME_SLOTS)
        raise RuntimeError(f"Could not match '{requested_time}' to a supported slot. Use one of: {valid}")

    return RedeliveryPlan(
        carrier=recognition.carrier,
        tracking_number=recognition.tracking_number,
        phone_number=recognition.booking_phone_number,
        requested_time=requested_time,
        time_slot=time_slot,
        confidence=recognition.confidence,
        notes=recognition.notes,
        user_summary=f"Ready to book {time_slot}.",
    )


async def plan_driver_call(
    image_path: str,
    progress: ProgressCallback | None = None,
) -> DriverCallPlan:
    if progress:
        await progress("Agent is reading the slip and preparing a same-day driver call...")

    agent = build_driver_call_planning_agent()
    result = await Runner.run(
        agent,
        input=(
            f"Slip image path: {image_path}\n"
            "Goal: call the driver or depot today to ask for same-day redelivery."
        ),
    )
    plan = _coerce_call_plan(result.final_output)

    override_phone = os.getenv("DRIVER_PHONE_NUMBER")
    if override_phone:
        plan = plan.model_copy(update={"driver_phone_number": override_phone})

    if not plan.driver_phone_number:
        raise RuntimeError(
            "Agent could not find a driver phone number. Set DRIVER_PHONE_NUMBER "
            "or use a slip that shows the driver/depot number."
        )

    normalized_phone = normalize_japan_phone_for_call(plan.driver_phone_number)
    if not normalized_phone:
        raise RuntimeError(f"Driver phone number is not callable: {plan.driver_phone_number}")
    if normalized_phone == normalize_japan_phone_for_call(DEFAULT_PHONE_NUMBER) and not override_phone:
        raise RuntimeError(
            "Agent only found the demo fallback phone number. Set DRIVER_PHONE_NUMBER "
            "or use a slip that shows the driver/depot number."
        )

    plan = plan.model_copy(update={"driver_phone_number": normalized_phone})
    plan = plan.model_copy(update={"objective": build_short_driver_call_objective(plan.tracking_number)})
    if progress:
        await progress(f"Agent prepared a call to {normalized_phone}.")
    return plan


def plan_driver_call_from_recognition(recognition: SlipRecognition) -> DriverCallPlan:
    override_phone = os.getenv("DRIVER_PHONE_NUMBER")
    driver_phone = override_phone or recognition.phone_number
    if not driver_phone:
        raise RuntimeError(
            "Could not find a driver phone number. Set DRIVER_PHONE_NUMBER "
            "or use a slip that shows the driver/depot number."
        )

    normalized_phone = normalize_japan_phone_for_call(driver_phone)
    if not normalized_phone:
        raise RuntimeError(f"Driver phone number is not callable: {driver_phone}")
    if normalized_phone == normalize_japan_phone_for_call(DEFAULT_PHONE_NUMBER) and not override_phone:
        raise RuntimeError(
            "Only found the demo fallback phone number. Set DRIVER_PHONE_NUMBER "
            "or use a slip that shows the driver/depot number."
        )

    return DriverCallPlan(
        carrier=recognition.carrier,
        tracking_number=recognition.tracking_number,
        driver_phone_number=normalized_phone,
        objective=build_short_driver_call_objective(recognition.tracking_number),
        confidence=recognition.confidence,
        notes=recognition.notes,
        user_summary=f"Ready to call {normalized_phone}.",
    )


async def book_confirmed_redelivery(
    plan: RedeliveryPlan,
    progress: ProgressCallback | None = None,
) -> BookingResult:
    if not plan.tracking_number:
        raise RuntimeError("Cannot book without a tracking number.")
    if not plan.phone_number:
        raise RuntimeError("Cannot book without a phone number.")

    if progress:
        await progress(f"Agent is booking {plan.time_slot} now...")

    agent = build_booking_agent()
    result = await Runner.run(
        agent,
        input=plan.model_dump_json(),
    )
    booking_result = _coerce_booking_result(result.final_output)

    if progress:
        await progress(booking_result.user_summary)
    return booking_result


async def call_confirmed_driver(
    plan: DriverCallPlan,
    progress: ProgressCallback | None = None,
) -> DriverCallResult:
    if not plan.driver_phone_number:
        raise RuntimeError("Cannot call without a driver phone number.")

    if progress:
        await progress(f"Agent is calling {plan.driver_phone_number} now...")

    agent = build_driver_call_agent()
    result = await Runner.run(
        agent,
        input=plan.model_dump_json(),
    )
    call_result = _coerce_call_result(result.final_output)

    if progress:
        await progress(call_result.user_summary)
    return call_result


def format_plan_confirmation(plan: RedeliveryPlan) -> str:
    return (
        "I found this booking plan:\n"
        f"Carrier: {plan.carrier}\n"
        f"Tracking: {plan.tracking_number}\n"
        f"Phone: {plan.phone_number}\n"
        f"Requested: {plan.requested_time}\n"
        f"Slot: {plan.time_slot}\n\n"
        "Reply yes to book it, or no to cancel."
    )


def format_driver_call_confirmation(plan: DriverCallPlan) -> str:
    return (
        "I found this driver-call plan:\n"
        f"Carrier: {plan.carrier}\n"
        f"Tracking: {plan.tracking_number or 'not found'}\n"
        f"Call: {plan.driver_phone_number}\n"
        f"Goal: {plan.objective}\n\n"
        "Reply yes to call the driver now, or no to cancel."
    )


def format_agent_trace(plan: RedeliveryPlan, result: BookingResult) -> str:
    status = "booked" if result.success else "booking failed"
    return (
        "Agent trace:\n"
        f"1. Read {plan.carrier} slip and found tracking {plan.tracking_number}\n"
        f"2. Matched \"{plan.requested_time}\" to {plan.time_slot}\n"
        "3. Waited for your confirmation\n"
        f"4. Ran browser booking automation: {status}"
    )


def format_driver_call_trace(plan: DriverCallPlan, result: DriverCallResult) -> str:
    status = result.status or ("started" if result.success else "failed")
    return (
        "Agent trace:\n"
        f"1. Read {plan.carrier} slip and found tracking {plan.tracking_number or 'unknown'}\n"
        "2. Built a Japanese same-day redelivery call objective\n"
        "3. Waited for your confirmation\n"
        f"4. Started Twilio/OpenAI realtime voice call: {status}"
    )


def build_short_driver_call_objective(tracking_number: str | None) -> str:
    tracking = tracking_number or "不明"
    return (
        "日本語で短く電話してください。全体を20秒以内に収めます。"
        "一文ずつ、余計な説明なし。"
        f"最初に「再配達の件です。伝票番号は{tracking}です。今日中の再配達は可能ですか？」と聞く。"
        "可能なら時間だけ確認してお礼を言って終了。"
        "無理なら「最短はいつですか？」だけ聞いて、お礼を言って終了。"
    )


def get_driver_call_status(call_sid: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{VOICE_AGENT_SERVER_URL.rstrip('/')}/calls/{call_sid}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json_loads(response.read().decode("utf-8"))


def summarize_driver_call_outcome(record: dict[str, Any]) -> DriverCallOutcome:
    status = str(record.get("status") or "")
    transcript = transcript_text(record)
    driver_text = transcript_text(record, roles={"user", "unknown"})
    normalized = driver_text.lower()

    negative_markers = (
        "too late",
        "not possible",
        "can't today",
        "cannot today",
        "no today",
        "今日は無理",
        "本日は無理",
        "今日中は無理",
        "できません",
        "難しい",
    )
    positive_markers = (
        "possible",
        "can today",
        "できます",
        "可能",
        "伺います",
        "届け",
        "配達できます",
    )

    today_available: bool | None = None
    if any(marker in normalized for marker in negative_markers) or any(
        marker in driver_text for marker in negative_markers
    ):
        today_available = False
    elif any(marker in normalized for marker in positive_markers) or any(
        marker in driver_text for marker in positive_markers
    ):
        today_available = True

    if today_available is False:
        summary = "Driver said same-day redelivery is not available."
        next_step = "Use the form flow to book tomorrow."
    elif today_available is True:
        summary = "Driver indicated same-day redelivery is possible."
        next_step = "No form booking is needed unless the driver asked for it."
    elif status == "error":
        summary = f"Call ended with an error: {record.get('error') or 'unknown'}"
        next_step = "Try the form flow or call again."
    else:
        summary = "Call finished, but the outcome was unclear."
        next_step = "Check the transcript or use the form flow."

    return DriverCallOutcome(
        status=status,
        today_available=today_available,
        summary=summary,
        next_step=next_step,
        transcript=transcript,
    )


def transcript_text(record: dict[str, Any], roles: set[str] | None = None) -> str:
    turns = record.get("turns") or []
    lines: list[str] = []
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "unknown")
            if roles is not None and role not in roles:
                continue
            text = str(turn.get("text") or "").strip()
            if text:
                lines.append(f"{role}: {text}")
    return "\n".join(lines)


def format_driver_call_outcome(outcome: DriverCallOutcome) -> str:
    message = (
        "Call outcome:\n"
        f"Status: {outcome.status or 'unknown'}\n"
        f"Summary: {outcome.summary}\n"
        f"Next: {outcome.next_step}"
    )
    if outcome.transcript:
        message += f"\n\nTranscript:\n{trim_text(outcome.transcript, 900)}"
    return message


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def normalize_japan_phone_for_call(phone_number: str | None) -> str | None:
    if not phone_number:
        return None
    value = phone_number.strip()
    if value.startswith("+"):
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"+{digits}" if digits else None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("81"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+81{digits[1:]}"
    return f"+{digits}"


def json_bytes(payload: dict[str, Any]) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def json_loads(text: str) -> dict[str, Any]:
    import json

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object")
    return payload


async def _main_async(args: argparse.Namespace) -> None:
    if args.call_driver:
        call_plan = await plan_driver_call(args.image)
        print(call_plan.model_dump_json(indent=2, ensure_ascii=False))
        if args.call:
            call_result = await call_confirmed_driver(call_plan)
            print(call_result.model_dump_json(indent=2, ensure_ascii=False))
            print(format_driver_call_trace(call_plan, call_result))
    else:
        plan = await plan_redelivery(args.image, args.time)
        print(plan.model_dump_json(indent=2, ensure_ascii=False))
        if args.book:
            result = await book_confirmed_redelivery(plan)
            print(result.model_dump_json(indent=2, ensure_ascii=False))
            print(format_agent_trace(plan, result))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agents SDK redelivery workflow.")
    parser.add_argument("image", help="path to a redelivery slip image")
    parser.add_argument("time", nargs="?", default="around six pm", help="requested delivery time")
    parser.add_argument("--book", action="store_true", help="run the booking automation after planning")
    parser.add_argument("--call-driver", action="store_true", help="plan a same-day driver call")
    parser.add_argument("--call", action="store_true", help="start the voice-agent call after planning")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
