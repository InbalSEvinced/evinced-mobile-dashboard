#!/usr/bin/env python3
import asyncio, sys, os

# Support local dev: playwright may be installed in a non-standard location
_extra = '/sessions/epic-quirky-turing/.local/lib/python3.10/site-packages'
if os.path.isdir(_extra):
    sys.path.insert(0, _extra)

from playwright.async_api import async_playwright

BASE       = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR") or BASE
os.makedirs(OUTPUT_DIR, exist_ok=True)

html_path = os.path.join(OUTPUT_DIR, "mobile-products-dashboard.html")
pdf_path  = os.path.join(OUTPUT_DIR, "mobile-products-dashboard.pdf")

# Chromium executable: prefer env var, then well-known paths
CHROMIUM_PATHS = [
    os.environ.get("CHROMIUM_PATH", ""),
    "/ms-playwright/chromium_headless_shell-1208/chrome-linux64/chrome",
    "/ms-playwright/chromium-1208/chrome-linux64/chrome",
    "/sessions/epic-quirky-turing/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome",
]

async def main():
    chromium_exe = next((p for p in CHROMIUM_PATHS if p and os.path.isfile(p)), None)

    async with async_playwright() as p:
        launch_kwargs = dict(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        if chromium_exe:
            launch_kwargs["executable_path"] = chromium_exe

        browser = await p.chromium.launch(**launch_kwargs)
        page    = await browser.new_page()
        await page.set_viewport_size({"width": 1600, "height": 900})
        await page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)  # let Chart.js render

        await page.pdf(
            path=pdf_path,
            format="A3",
            landscape=True,
            print_background=True,
            margin={"top": "8mm", "bottom": "8mm", "left": "8mm", "right": "8mm"},
            scale=0.82,
        )
        print(f"PDF saved → {pdf_path}")
        print(f"Size: {os.path.getsize(pdf_path):,} bytes")
        await browser.close()

asyncio.run(main())
