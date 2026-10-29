import os
import sys
import logging
import socket
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from playwright.async_api import async_playwright

import database as db

# Load credentials from .env
ENV_PATH = r"c:\Users\santh\Downloads\.env"
load_dotenv(dotenv_path=ENV_PATH)

EMAIL = os.getenv("NESTORA_EMAIL")
PASSWORD = os.getenv("NESTORA_PASSWORD")
BASE_URL = "https://nestora.rathinam.in/"

# Mobile Push Notification Topic (ntfy.sh - free push notifications to phone)
NTFY_TOPIC = "nestora_food_booking_arul"

app = FastAPI(title="Nestora Mobile App with Push Notifications & DB")

# Initialize database on module load
db.init_db()

booking_state = {
    "status": "idle", # idle, running, success, error
    "last_run": None,
    "last_auto_date": None,
    "message": "Auto-booking system ready. Notification active.",
    "logs": []
}

def send_mobile_push_notification(title: str, message: str):
    """Sends real push notification directly to user's mobile phone via ntfy.sh"""
    try:
        url = f"https://ntfy.sh/{NTFY_TOPIC}"
        req = urllib.request.Request(
            url,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "bento,tada,hamburger"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[Push Notification Sent] Status Code: {resp.status}")
    except Exception as e:
        print(f"[Push Notification Warning] Could not send: {e}")

def add_log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    # Clean non-ASCII characters to prevent Windows CP1252 charmap encoding crash
    clean_msg = msg.encode("ascii", "ignore").decode("ascii")
    formatted = f"[{timestamp}] {clean_msg}"
    print(formatted)
    booking_state["logs"].append(formatted)
    booking_state["message"] = clean_msg

async def run_booking_task(trigger_type: str = "Manual"):
    booking_state["status"] = "running"
    booking_state["logs"] = []
    add_log(f"Starting {trigger_type} Nestora food booking for Today and Tomorrow...")

    if not EMAIL or not PASSWORD:
        booking_state["status"] = "error"
        add_log("ERROR: NESTORA_EMAIL / NESTORA_PASSWORD not set in .env file.")
        db.add_booking_record(
            target_date=datetime.now().strftime("%Y-%m-%d"),
            meals_booked="None",
            status="FAILED",
            log_text="Missing credentials"
        )
        send_mobile_push_notification(
            title="Nestora Food Booking Failed",
            message="Error: Missing NESTORA_EMAIL or NESTORA_PASSWORD in .env file."
        )
        return

    total_booked_count = 0
    summary_meals = []
    target_date_str = datetime.now().strftime("%Y-%m-%d")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            add_log(f"Opening {BASE_URL}...")
            await page.goto(BASE_URL, wait_until="networkidle")

            # Check for Microsoft SSO
            await page.wait_for_selector("text=SIGN IN WITH MICROSOFT", timeout=15000)
            add_log("Logging in via Microsoft SSO...")
            await page.click("text=SIGN IN WITH MICROSOFT")

            # Fill Email
            await page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=15000)
            await page.fill("input[type='email'], input[name='loginfmt']", EMAIL)
            await page.click("input[type='submit'], button:has-text('Next'), #idSIButton9")
            add_log("Submitted Microsoft email.")

            # Fill Password
            await page.wait_for_selector("input[type='password'], input[name='passwd']", timeout=15000)
            await page.fill("input[type='password'], input[name='passwd']", PASSWORD)
            await page.click("input[type='submit'], button:has-text('Sign in'), #idSIButton9")
            add_log("Submitted Microsoft password.")

            # Stay signed in prompt
            await asyncio.sleep(3)
            if "login.microsoftonline.com" in page.url:
                stay_btn = page.locator("input[type='submit'][value='Yes'], #idSIButton9, button:has-text('Yes')")
                if await stay_btn.is_visible():
                    await stay_btn.click()

            await page.wait_for_url("**/students/**", timeout=30000)
            add_log("Logged into Resident Portal successfully.")

            # Navigate to Food Token
            await page.wait_for_selector("text=Food Token", timeout=15000)
            await page.click("text=Food Token")
            await page.wait_for_url("**/food-token**", timeout=15000)
            await asyncio.sleep(2)
            add_log("Navigated to Food Token page.")

            async def process_tab(tab_name):
                nonlocal total_booked_count
                add_log(f"--- Checking {tab_name} Meals ---")
                tab_btn = page.locator(f"button:has-text('{tab_name}')").first
                if await tab_btn.is_visible():
                    await tab_btn.click()
                    await asyncio.sleep(2)

                count = 0
                while True:
                    unbooked = page.locator("button:has-text('BOOK')").filter(has_not_text="VIEW PASS").filter(has_not_text="TOMORROW").filter(has_not_text="TODAY")
                    if await unbooked.count() == 0:
                        break
                    
                    try:
                        target = unbooked.first
                        add_log(f"Booking {tab_name} meal #{count + 1}...")
                        await target.click()
                        count += 1
                        total_booked_count += 1
                        await asyncio.sleep(2)
                    except Exception as err:
                        add_log(f"Error booking meal: {err}")
                        break

                if count > 0:
                    summary_meals.append(f"{tab_name}: {count} booked")
                    add_log(f"SUCCESS: Booked {count} meal(s) for {tab_name}!")
                else:
                    summary_meals.append(f"{tab_name}: All Booked")
                    add_log(f"{tab_name} Meals: All available meals are already booked or closed.")

            await process_tab("TODAY")
            await process_tab("TOMORROW")

            booking_state["status"] = "success"
            msg = f"Automatic food booking completed successfully! ({trigger_type})"
            booking_state["message"] = msg
            booking_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            booking_state["last_auto_date"] = target_date_str

            # Record in SQLite Database
            db.add_booking_record(
                target_date=target_date_str,
                meals_booked=" | ".join(summary_meals) if summary_meals else "All Booked",
                status="SUCCESS",
                log_text="\n".join(booking_state["logs"])
            )

            # SEND MOBILE PUSH NOTIFICATION TO PHONE!
            push_msg = f"Nestora Food Booked!\nToday & Tomorrow meals (Breakfast, Lunch, Snacks, Dinner) confirmed.\nTime: {datetime.now().strftime('%I:%M %p')}"
            send_mobile_push_notification(
                title="Nestora Food Booked!",
                message=push_msg
            )
            add_log("Mobile Push Notification sent to your phone!")

        except Exception as e:
            booking_state["status"] = "error"
            clean_err = str(e).encode("ascii", "ignore").decode("ascii")
            add_log(f"ERROR: {clean_err}")
            
            db.add_booking_record(
                target_date=target_date_str,
                meals_booked="None",
                status="FAILED",
                log_text=clean_err
            )

            send_mobile_push_notification(
                title="Nestora Booking Error",
                message=f"Booking failed: {clean_err[:100]}"
            )
        finally:
            await browser.close()


# Automatic Daily Scheduler Task (Runs Every Day at 8:00 PM / 20:00)
async def auto_scheduler_task():
    add_log("Automatic Daily 8:00 PM Scheduler started in background.")
    while True:
        try:
            settings = db.get_settings()
            if settings.get("auto_booking_enabled") == 1:
                now = datetime.now()
                target_time_str = settings.get("booking_time", "20:00")
                current_time_str = now.strftime("%H:%M")
                current_date_str = now.strftime("%Y-%m-%d")

                # Trigger at 8:00 PM (or user set time) if not run yet today
                if current_time_str == target_time_str and booking_state["last_auto_date"] != current_date_str:
                    if booking_state["status"] != "running":
                        add_log(f"Daily Auto-Booking triggered at 8:00 PM ({target_time_str})!")
                        await run_booking_task(trigger_type="8:00 PM Auto-Scheduler")

        except Exception as err:
            print("Scheduler loop error:", err)

        await asyncio.sleep(30)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_scheduler_task())


@app.get("/", response_class=HTMLResponse)
def get_home():
    static_html = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_html):
        with open(static_html, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Nestora Mobile Server Running</h1>"


@app.post("/api/book-tomorrow")
async def trigger_booking(background_tasks: BackgroundTasks):
    if booking_state["status"] == "running":
        return JSONResponse({"status": "already_running", "message": "Booking is already in progress..."})

    background_tasks.add_task(run_booking_task, "Manual 1-Tap")
    return JSONResponse({"status": "started", "message": "Booking process initiated!"})


@app.get("/api/status")
def get_status():
    res = dict(booking_state)
    res["settings"] = db.get_settings()
    res["ntfy_topic"] = NTFY_TOPIC
    return JSONResponse(res)


@app.get("/api/history")
def get_history():
    return JSONResponse(db.get_booking_history())


@app.get("/api/stats")
def get_stats():
    return JSONResponse(db.get_booking_stats())


@app.get("/api/settings")
def get_settings():
    return JSONResponse(db.get_settings())


@app.post("/api/settings")
def save_settings(data: dict):
    db.update_settings(
        auto_booking_enabled=int(data.get("auto_booking_enabled", 1)),
        booking_time=str(data.get("booking_time", "20:00")),
        book_today=int(data.get("book_today", 1)),
        book_tomorrow=int(data.get("book_tomorrow", 1))
    )
    return JSONResponse({"status": "updated", "settings": db.get_settings()})


if __name__ == "__main__":
    import uvicorn
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print("\n========================================================")
    print("NESTORA AUTOMATIC DAILY FOOD BOOKING SERVER IS RUNNING!")
    print(f"Mobile Access (on Wi-Fi): http://{local_ip}:8000")
    print(f"PC Access:                 http://localhost:8000")
    print(f"Mobile Push Topic:         https://ntfy.sh/{NTFY_TOPIC}")
    print("========================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
