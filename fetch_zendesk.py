#!/usr/bin/env python3
"""
Fetch ticket counts per account from Zendesk.
Writes zendesk_tickets.json with total and monthly ticket counts per tenant.

Requires env vars: ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN
"""
import json, os, urllib.request, urllib.parse, base64
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))

SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "")
EMAIL     = os.environ.get("ZENDESK_EMAIL", "")
API_TOKEN = os.environ.get("ZENDESK_API_TOKEN", "")

if not all([SUBDOMAIN, EMAIL, API_TOKEN]):
    raise EnvironmentError(
        "Missing Zendesk credentials. Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, "
        "and ZENDESK_API_TOKEN in your .env file."
    )

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = base64.b64encode(f"{EMAIL}/token:{API_TOKEN}".encode()).decode()
HEADERS = {"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"}

now = datetime.now(timezone.utc)
month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
month_start_str = month_start.strftime("%Y-%m-%dT%H:%M:%SZ")

def zendesk_get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def search_tickets(query):
    """Search Zendesk tickets and return count."""
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/search.json?query={encoded}&count_only=true"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
            return data.get("count", 0)
    except Exception as e:
        print(f"  ⚠ search error: {e}")
        return 0

def main():
    rows_path = os.path.join(BASE, "rows_with_sa.json")
    if not os.path.exists(rows_path):
        raise FileNotFoundError(f"{rows_path} not found — run fetch_with_sa.py first")

    rows = json.load(open(rows_path))
    tenant_names = sorted(set(r["tenantName"] for r in rows if r.get("tenantName")))
    print(f"Fetching Zendesk ticket counts for {len(tenant_names)} tenants…")

    results = {}
    for i, name in enumerate(tenant_names, 1):
        print(f"  [{i}/{len(tenant_names)}] {name}…", end=" ", flush=True)

        # All-time tickets
        tickets_all = search_tickets(f'type:ticket organization:"{name}"')

        # This month's tickets
        tickets_month = search_tickets(
            f'type:ticket organization:"{name}" created>={month_start_str}'
        )

        results[name] = {
            "tickets_all":   tickets_all,
            "tickets_month": tickets_month,
        }
        print(f"all={tickets_all}, this month={tickets_month}")

    out = os.path.join(BASE, "zendesk_tickets.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} accounts → {out}")

if __name__ == "__main__":
    main()
