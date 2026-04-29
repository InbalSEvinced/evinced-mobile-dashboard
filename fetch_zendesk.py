#!/usr/bin/env python3
"""
Fetch Zendesk mobile/MFA tickets → zendesk_severity.json, zendesk_by_type.json, zendesk_monthly.json

Authentication: uses ZENDESK_EMAIL + ZENDESK_API_TOKEN env vars (or hardcoded below).
Run: python3 fetch_zendesk.py
"""
import urllib.request, urllib.parse, json, base64, os
from collections import defaultdict
from datetime import date

BASE   = os.path.dirname(os.path.abspath(__file__))
DOMAIN = os.getenv("ZENDESK_DOMAIN",    "https://evinced.zendesk.com")
EMAIL  = os.getenv("ZENDESK_EMAIL",     "inbal.sanado@evinced.com")
TOKEN  = os.getenv("ZENDESK_API_TOKEN", "hfDZeakYL7Zs7QYjFjFJucGAX4oAo2p9bDQAAUzQ")

creds   = base64.b64encode(f"{EMAIL}/token:{TOKEN}".encode()).decode()
HEADERS = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

def fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# ── Fetch all mobile/MFA tickets ──────────────────────────────────────────────
all_tickets = []
org_map     = {}   # org_id → org name (sideloaded)
query = "type:ticket (mobile OR MFA)"
url   = f"{DOMAIN}/api/v2/search.json?" + urllib.parse.urlencode({"query": query, "per_page": 100, "include": "organizations"})

while url:
    data = fetch_page(url)
    for org in data.get("organizations", []):
        org_map[org["id"]] = org["name"]
    all_tickets.extend(data.get("results", []))
    url = data.get("next_page")
    print(f"  Fetched {len(all_tickets)} tickets so far…")

print(f"Total: {len(all_tickets)} mobile/MFA tickets")

# ── Severity breakdown ────────────────────────────────────────────────────────
priority_count = defaultdict(int)
status_count   = defaultdict(int)
by_month       = defaultdict(int)

for t in all_tickets:
    p = (t.get("priority") or "normal").title()
    priority_count[p] += 1
    status_count[t.get("status", "unknown")] += 1
    month = t.get("created_at", "")[:7]
    if month:
        by_month[month] += 1

# ── By product type (subject classification) ──────────────────────────────────
mfa_count = sdk_count = other_count = 0
for t in all_tickets:
    text = ((t.get("subject") or "") + " " + (t.get("description") or "")[:200]).lower()
    has_mfa = "mfa" in text or "mobile flow" in text
    has_sdk = any(k in text for k in ["sdk", "espresso", "xcui", "appium", "wdio"])
    if has_mfa:
        mfa_count += 1
    elif has_sdk:
        sdk_count += 1
    else:
        other_count += 1

# ── Save outputs ──────────────────────────────────────────────────────────────
sev = [{"severity": k, "count": v} for k, v in sorted(priority_count.items(), key=lambda x: -x[1])]
json.dump(sev, open(os.path.join(BASE, "zendesk_severity.json"), "w"), indent=2)

types = [
    {"type": "MFA",           "count": mfa_count},
    {"type": "Mobile SDK",    "count": sdk_count},
    {"type": "General Mobile","count": other_count},
]
json.dump(types, open(os.path.join(BASE, "zendesk_by_type.json"), "w"), indent=2)

monthly = [{"month": k, "count": v} for k, v in sorted(by_month.items())]
json.dump(monthly, open(os.path.join(BASE, "zendesk_monthly.json"), "w"), indent=2)

# ── Raw tickets (for dynamic date filtering in dashboard) ─────────────────────
tickets_out = []
for t in all_tickets:
    date_str = (t.get("created_at") or "")[:10]   # YYYY-MM-DD
    if not date_str:
        continue
    text = ((t.get("subject") or "") + " " + (t.get("description") or "")[:200]).lower()
    has_mfa = "mfa" in text or "mobile flow" in text
    has_sdk = any(k in text for k in ["sdk", "espresso", "xcui", "appium", "wdio"])
    ticket_type = "MFA" if has_mfa else ("Mobile SDK" if has_sdk else "General Mobile")
    org_id   = t.get("organization_id")
    org_name = org_map.get(org_id, "") if org_id else ""
    tickets_out.append({
        "created_at":   t.get("created_at", ""),
        "subject":      t.get("subject", ""),
        "priority":     t.get("priority") or "normal",
        "status":       t.get("status", ""),
        "type":         ticket_type,
        "organization": org_name,
    })
json.dump(tickets_out, open(os.path.join(BASE, "zendesk_tickets.json"), "w"), indent=2)

# Current month
cur_month = date.today().strftime("%Y-%m")
cur_count = by_month.get(cur_month, 0)
print(f"Saved zendesk_severity.json, zendesk_by_type.json, zendesk_monthly.json, zendesk_tickets.json ({len(tickets_out)} tickets)")
print(f"Current month ({cur_month}): {cur_count} tickets")
print(f"By status: {dict(status_count)}")
