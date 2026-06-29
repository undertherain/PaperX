import argparse
import asyncio
import os
import subprocess
import sys
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from slip_recognition import SlipRecognition, recognize_slip
from time_slots import VALID_TIME_SLOTS, normalize_time_slot

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_AGENT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

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


async def _main_async(args: argparse.Namespace) -> None:
    plan = await plan_redelivery(args.image, args.time)
    print(plan.model_dump_json(indent=2, ensure_ascii=False))
    if args.book:
        result = await book_confirmed_redelivery(plan)
        print(result.model_dump_json(indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agents SDK redelivery workflow.")
    parser.add_argument("image", help="path to a redelivery slip image")
    parser.add_argument("time", help="requested delivery time, e.g. 'around six pm'")
    parser.add_argument("--book", action="store_true", help="run the booking automation after planning")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
