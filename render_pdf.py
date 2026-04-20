#!/usr/bin/env python3
"""Render the mobile-products-dashboard HTML to PDF using Playwright/Chromium.
Handles Playwright installation automatically if needed."""
import asyncio, sys, os, subprocess, glob

BASE    = os.path.dirname(os.path.abspath(__file__))
OUTPUTS = os.environ.get("OUTPUT_DIR") or os.path.join(BASE, "output")
os.makedirs(OUTPUTS, exist_ok=True)

HTML_PATH = os.path.join(OUTPUTS, "mobile-products-dashboard.html")
PDF_PATH  = os.path.join(OUTPUTS, "mobile-products-dashboard.pdf")

def find_chromium():
    """Find Chromium binary installed by Playwright, searching common cache locations.
    Returns None if not found; Playwright will then locate its own binary at launch."""
    patterns = [
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"),
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"),
        "/ms-playwright/chromium-*/chrome-linux/chrome",
        "/ms-playwright/chromium-*/chrome-linux64/chrome",
        "/root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return sorted(matches)[-1]  # latest version
    return None

def ensure_playwright():
    """Ensure the playwright package is importable. Browser binary is located
    either via find_chromium() or left to Playwright's own resolution."""
    try:
        import playwright  # noqa: F401
        return find_chromium()
    except ImportError:
        pass

    print("Installing Playwright…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright",
                           "--break-system-packages", "-q"])
    print("Installing Chromium…")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    return find_chromium()

async def render(chrome_path):
    # Add site-packages to path so playwright is importable
    for sp in glob.glob(os.path.expanduser("~/.local/lib/python*/site-packages")):
        if sp not in sys.path:
            sys.path.insert(0, sp)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        launch_kwargs = {
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        }
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        browser = await p.chromium.launch(**launch_kwargs)
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1600, "height": 900})
        await page.goto(f"file://{HTML_PATH}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)  # let Chart.js render

        await page.pdf(
            path=PDF_PATH,
            format="A3",
            landscape=True,
            print_background=True,
            margin={"top": "8mm", "bottom": "8mm", "left": "8mm", "right": "8mm"},
            scale=0.82,
        )
        size = os.path.getsize(PDF_PATH)
        print(f"PDF saved → {PDF_PATH}  ({size:,} bytes)")
        await browser.close()

if __name__ == "__main__":
    chrome = ensure_playwright()
    print(f"Using Chromium: {chrome or '(Playwright default)'}")
    asyncio.run(render(chrome))
