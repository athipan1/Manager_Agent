from pathlib import Path

from playwright.sync_api import sync_playwright


DASHBOARD_URL = "http://127.0.0.1:8000/dashboard"
OUTPUT_DIR = Path("dashboard-artifacts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1600}, device_scale_factor=1)
    page.goto(DASHBOARD_URL, wait_until="networkidle")
    page.screenshot(path=str(OUTPUT_DIR / "dashboard-screenshot.png"), full_page=True)
    browser.close()
