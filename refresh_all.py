#!/usr/bin/env python3
"""
Mobile Products Dashboard — Daily Refresh Orchestrator
Runs all 4 steps in sequence, then posts the result to Slack #mobile_analytics.

Steps:
  1. fetch_with_sa.py         — pull 14-day Coralogix scan data
  2. fetch_latest_scan_dates.py — pull per-tenant last-scan timestamps
  3. rebuild_dashboard_v4.py  — generate HTML dashboard
  4. render_pdf.py            — render PDF from HTML

After success, posts a summary message + PDF link to Slack #mobile_analytics.
"""
import subprocess, sys, os, json, urllib.request, urllib.error
from datetime import datetime, timezone

BASE    = os.path.dirname(os.path.abspath(__file__))
OUTPUTS = os.path.join(BASE, "..")

SLACK_TOKEN   = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = "C0AT76PV6F6"   # #mobile_analytics

STEPS = [
    ("Fetching scan data from Coralogix",       os.path.join(BASE, "fetch_with_sa.py")),
    ("Fetching latest scan dates",               os.path.join(BASE, "fetch_latest_scan_dates.py")),
    ("Fetching HubSpot account metadata",        os.path.join(BASE, "fetch_hubspot.py")),
    ("Fetching Zendesk ticket counts",           os.path.join(BASE, "fetch_zendesk.py")),
    ("Rebuilding HTML dashboard",                os.path.join(BASE, "rebuild_dashboard_v4.py")),
    ("Rendering PDF",                            os.path.join(BASE, "render_pdf.py")),
]

def run_step(label, script):
    print(f"\n{'='*60}")
    print(f"▶  {label}")
    print(f"{'='*60}")
    result = subprocess.run([sys.executable, script], capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {label} (exit {result.returncode})")

def post_slack(message):
    if not SLACK_TOKEN:
        print(f"[Slack] SLACK_BOT_TOKEN not set — skipping post.\nMessage would be:\n{message}")
        return
    payload = json.dumps({"channel": SLACK_CHANNEL, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {SLACK_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                print("[Slack] Message posted ✓")
            else:
                print(f"[Slack] Error: {data.get('error')}")
    except Exception as e:
        print(f"[Slack] Failed to post: {e}")

def main():
    start = datetime.now(timezone.utc)
    print(f"\n🔄  Mobile Dashboard Refresh — {start.strftime('%Y-%m-%d %H:%M UTC')}")

    errors = []
    for label, script in STEPS:
        try:
            run_step(label, script)
        except RuntimeError as e:
            errors.append(str(e))
            print(f"❌  {e}")
            break

    finish = datetime.now(timezone.utc)
    elapsed = int((finish - start).total_seconds())
    today = finish.strftime("%B %d, %Y")

    if errors:
        msg = (f":x: *Mobile Products Dashboard refresh failed* ({today})\n"
               f"Error: {errors[0]}\n"
               f"Duration: {elapsed}s")
    else:
        # Read HTML size as a proxy for data freshness
        html_path = os.path.join(OUTPUTS, "mobile-products-dashboard.html")
        html_size = os.path.getsize(html_path) // 1024 if os.path.exists(html_path) else 0
        msg = (f":white_check_mark: *Mobile Products Dashboard refreshed* — {today}\n"
               f"Data: last 14 days · Coralogix + Pendo\n"
               f"HTML: {html_size} KB  |  Refresh took {elapsed}s\n"
               f"Open on internal server: http://localhost:8080/mobile-products-dashboard.html")

    post_slack(msg)
    print(f"\n{'='*60}")
    print(f"{'✅  Done' if not errors else '❌  Failed'} in {elapsed}s")
    print(f"{'='*60}\n")
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
