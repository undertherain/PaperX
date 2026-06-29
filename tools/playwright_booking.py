import sys
import os
import asyncio
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from time_slots import VALID_TIME_SLOTS, normalize_time_slot

async def book_redelivery(tracking, phone, timeslot):
    timeslot = normalize_time_slot(timeslot)
    if timeslot not in VALID_TIME_SLOTS:
        valid = ", ".join(VALID_TIME_SLOTS)
        raise ValueError(f"Unsupported time slot '{timeslot}'. Use one of: {valid}")

    async with async_playwright() as p:
        # Launch browser in non-headless mode so the demo is visible
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=150,
            executable_path='/snap/bin/chromium'
        )
        page = await browser.new_page()
        
        # Get absolute path to the fake site
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = f"file://{current_dir}/fake_booking_site/index.html"
        
        print(f"Opening {html_path}...")
        await page.goto(html_path)
        
        print("Filling tracking number...")
        await page.fill('#tracking-number', tracking)
        
        print("Filling phone number...")
        await page.fill('#phone-number', phone)
        
        print("Selecting date (tomorrow)...")
        await page.select_option('#desired-date', index=2)
        
        print(f"Selecting timeslot: {timeslot}...")
        await page.select_option('#desired-time', timeslot)
        
        print("Submitting form...")
        await page.click('button[type="submit"]')
        
        # Wait a moment to show the success screen
        await page.wait_for_timeout(3000)
        
        print(f"✅ Success! Redelivery booked for {timeslot}.")
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python playwright_booking.py <tracking_number> <phone_number> <timeslot>")
        sys.exit(1)
        
    tracking = sys.argv[1]
    phone = sys.argv[2]
    timeslot = sys.argv[3]
    
    try:
        asyncio.run(book_redelivery(tracking, phone, timeslot))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
