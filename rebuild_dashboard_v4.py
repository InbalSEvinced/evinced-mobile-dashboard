#!/usr/bin/env python3
"""
Mobile Products Dashboard v5 — BigQuery edition
Changes vs v4:
  1. Last updated date in header
  2. All "Coralogix" → "BigQuery"
  3. Date range: 7 / 30 / 60 days + custom
  4. Zendesk pie chart by severity (loads zendesk_severity.json or uses placeholder)
  5. Weekend filter (toggle applies to whole dashboard)
  6. Row highlighting: new tenants (green), renewal (amber), biggest scan drop (red)
  7. Removed avg issues/scan + critical/scan KPIs
  8. platformName (os_name) used as SDK "variant"
  9. Updated query: starts 2025-01-01 (reflected in fetch_with_sa.py)
"""
import json, os
from collections import defaultdict
from datetime import datetime as _dt, date as _date, timedelta as _td

BASE = os.path.dirname(os.path.abspath(__file__))

def load_json(path, fallback=None):
    try:
        return json.load(open(path))
    except Exception:
        return fallback

# ── Load data ──────────────────────────────────────────────────────────────────
MNT_CANDIDATE = os.path.join(BASE, "mnt/evinced-dashboard")
MNT = MNT_CANDIDATE if os.path.isdir(MNT_CANDIDATE) else BASE

# Fine-grained user-level rows (last 14 days) — for detail table
rows = load_json(os.path.join(MNT, "rows_with_sa.json"), [])

# 90-day daily aggregated rows — for charts + comparisons
daily_90d = load_json(os.path.join(MNT, "daily_rows_90d.json"), [])

# Latest scan dates per tenant
latest_scan = load_json(os.path.join(MNT, "latest_scan_dates.json"), {})

# Zendesk data (live from API)
zendesk_severity = load_json(os.path.join(MNT, "zendesk_severity.json"), None)
zendesk_by_type  = load_json(os.path.join(MNT, "zendesk_by_type.json"),  None)
zendesk_monthly  = load_json(os.path.join(MNT, "zendesk_monthly.json"),  None)
_zd_tickets_raw  = load_json(os.path.join(MNT, "zendesk_tickets.json"),  [])

LAST_UPDATED = _date.today().strftime("%B %d, %Y")

# ── SDK type normalization ─────────────────────────────────────────────────────
SDK_TYPE_NORM = {
    "MFA": "MFA", "mfa": "MFA",
    "mobileflowanalyzer": "MFA", "mobile_flow_analyzer": "MFA",
    "MOBILE_FLOW_ANALYZER": "MFA",
    "ESPRESSO_SDK": "Espresso", "espresso_sdk": "Espresso", "espresso": "Espresso",
    "WDIO_MOBILE_SDK": "WebdriverIO", "wdio_mobile_sdk": "WebdriverIO", "wdio": "WebdriverIO",
    "XCUISDK": "XCUITest", "xcuisdk": "XCUITest",
    "XCUI_SDK": "XCUITest", "xcui_sdk": "XCUITest",
    "APPIUM_JAVA_SDK": "Appium", "appium_java_sdk": "Appium",
    "APPIUM_PYTHON_SDK": "Appium", "appium_python_sdk": "Appium",
    "appium": "Appium",
    "MCP_SERVER_MOBILE": "MCP Server", "mcp_server_mobile": "MCP Server",
}

def norm_sdk_type(s):
    if not s: return "Unknown"
    return SDK_TYPE_NORM.get(s.strip()) or SDK_TYPE_NORM.get(s.strip().upper()) or s.strip()

for r in rows:
    r["sdkType"] = norm_sdk_type(r.get("sdkType", ""))
    # Use platformName (os_name) as SDK variant
    platform = r.get("platformName") or ""
    r["sdkVariant"] = platform if platform and platform.lower() not in ("null","none","") else None

for r in daily_90d:
    r["sdkType"] = norm_sdk_type(r.get("sdkType", ""))

# ── Internals ─────────────────────────────────────────────────────────────────
INTERNALS = {"Evinced Demo Account", "Evinced Dev Team", "GD", "Evinced Support"}

SDK_PRODUCT_TYPES = {"Espresso", "WebdriverIO", "XCUITest", "Appium", "MCP Server"}

# ── HubSpot data ───────────────────────────────────────────────────────────────
# stage: HubSpot deal stage — "Customer", "Churned", "Former Customer", etc.
# contract_end: "YYYY-MM-DD" or None — if expired AND stage != "Customer", tenant is excluded
HUBSPOT = {
    "Amazon Blink":         {"owner": "—",               "se": "Dominic Lucia",    "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 2,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "American Airlines":    {"owner": "Jacob Hume",      "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Auticon":              {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "—",             "is_new": False, "renewal": "2026-05-31", "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "BECU":                 {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Bank of Ireland":      {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Bell Media":           {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 1, "stage": "Customer",  "contract_end": None},
    "Booking":              {"owner": "Liam Ingleby",    "se": "Kevin Berg",       "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Canal Plus":           {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Capital One":          {"owner": "Navin Thadani",   "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 4,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Charter":              {"owner": "—",               "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Cigna":                {"owner": "Skye Hollins",    "se": "Justin Schaeffer", "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 5,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Comcast":              {"owner": "Jacob Hume",      "se": "Kevin Berg",       "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Costco":               {"owner": "—",               "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "CreditOne":            {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Evinced Demo Account": {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Evinced Dev Team":     {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Expedia Group":        {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": True,  "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Fidelity Investments": {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 4,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "GD":                   {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "HCAHealthcare":        {"owner": "—",               "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Huntington Bank":      {"owner": "Skye Hollins",    "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Hyatt":                {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Lufthansa":            {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Maximus":              {"owner": "Amandeep Dhillon","se": "Justin Schaeffer", "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Microsoft":            {"owner": "Ryan Patterson",  "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "NatWest":              {"owner": "Liam Ingleby",    "se": "Chris Keene",      "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Progressive":          {"owner": "Jacob Hume",      "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "SAP":                  {"owner": "Sam O'Meara",     "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Sainsburys":           {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Sky UK":               {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 3,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Subway":               {"owner": "Skye Hollins",    "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 1, "stage": "Customer",  "contract_end": None},
    "Verizon":              {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Yahoo":                {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
    "Zalando":              {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0, "stage": "Customer",  "contract_end": None},
}

# ── Exclude expired non-customers ──────────────────────────────────────────────
_today = _date.today().isoformat()
EXCLUDED_TENANTS = {
    name for name, v in HUBSPOT.items()
    if v.get("contract_end") and v["contract_end"] < _today and v.get("stage", "Customer") != "Customer"
}

# ── Zendesk — live data ────────────────────────────────────────────────────────
# Severity pie
if zendesk_severity:
    ZD_SEV_LABELS = [r["severity"] for r in zendesk_severity]
    ZD_SEV_VALUES = [r["count"] for r in zendesk_severity]
    ZD_TOTAL = sum(ZD_SEV_VALUES)
else:
    ZD_SEV_LABELS = ["Normal", "Low", "High", "Urgent"]
    ZD_SEV_VALUES = [12, 5, 4, 2]
    ZD_TOTAL = 23

# By type (MFA vs SDK vs General)
if zendesk_by_type:
    ZD_TYPE_LABELS = [r["type"] for r in zendesk_by_type]
    ZD_TYPE_VALUES = [r["count"] for r in zendesk_by_type]
else:
    ZD_TYPE_LABELS = ["MFA", "Mobile SDK", "General Mobile"]
    ZD_TYPE_VALUES = [5, 2, 1]

# Monthly trend
if zendesk_monthly:
    ZD_MONTH_LABELS = [r["month"] for r in zendesk_monthly[-12:]]  # last 12 months
    ZD_MONTH_VALUES = [r["count"] for r in zendesk_monthly[-12:]]
else:
    ZD_MONTH_LABELS, ZD_MONTH_VALUES = [], []

# Build per-ticket JS array for dynamic date filtering
ZD_TICKETS = []
for t in _zd_tickets_raw:
    date_str = (t.get("created_at") or "")[:10]   # YYYY-MM-DD
    if not date_str:
        continue
    text = ((t.get("subject") or "") + " " + (t.get("description") or "")[:200]).lower()
    has_mfa = "mfa" in text or "mobile flow" in text
    has_sdk = any(k in text for k in ["sdk", "espresso", "xcui", "appium", "wdio"])
    ticket_type = "MFA" if has_mfa else ("Mobile SDK" if has_sdk else "General Mobile")
    ZD_TICKETS.append({
        "date":     date_str,
        "priority": (t.get("priority") or "normal").title(),
        "type":     ticket_type,
        "status":   t.get("status", ""),
    })

# Current month ticket count from Zendesk
_cur_month = _date.today().strftime("%Y-%m")
CURRENT_MONTH_TICKETS = next((r["count"] for r in (zendesk_monthly or []) if r["month"] == _cur_month), 0)

# ── Derived summaries ──────────────────────────────────────────────────────────
def user_id(r): return r.get("email") or r.get("serviceAccountId") or None

# Filter out excluded tenants from all data
rows      = [r for r in rows      if r["tenantName"] not in EXCLUDED_TENANTS]
daily_90d = [r for r in daily_90d if r["tenantName"] not in EXCLUDED_TENANTS]

all_tenants    = sorted(set(r["tenantName"] for r in rows if r["tenantName"]))
ext_tenants    = [t for t in all_tenants if t not in INTERNALS]
total_scans    = sum(r["scans"] for r in rows)
unique_users   = len(set(user_id(r) for r in rows if user_id(r)))
new_count      = sum(1 for v in HUBSPOT.values() if v["is_new"])
renewal_count  = sum(1 for v in HUBSPOT.values() if v["renewal"])

# ── SDK type pie from 90d data ─────────────────────────────────────────────────
sdk_type_agg = defaultdict(int)
for r in daily_90d:
    sdk_type_agg[r["sdkType"]] += r["scans"]
SDK_TYPE_PIE = [{"sdkType": k, "scans": v} for k, v in sorted(sdk_type_agg.items(), key=lambda x: -x[1])]

# ── SDK type + platform (variant) stacked bar ─────────────────────────────────
sdk_tv_agg = defaultdict(int)
for r in daily_90d:
    platform = r.get("platformName") or "—"
    key = f"{r['sdkType']} / {platform}"
    sdk_tv_agg[key] += r["scans"]
SDK_TV_LIST = [{"label": k, "scans": v} for k, v in sorted(sdk_tv_agg.items(), key=lambda x: -x[1]) if v > 0]

# ── Detail rows (user-level, last 14 days) ────────────────────────────────────
det_agg = defaultdict(lambda: {"scans": 0, "sdkTypes": set()})
for r in rows:
    uid = user_id(r) or ""
    key = (r["tenantName"], uid)
    det_agg[key]["scans"]    += r["scans"]
    det_agg[key]["sdkTypes"].add(r["sdkType"])

detail_rows = []
for (tenant, uid), stats in sorted(det_agg.items(), key=lambda x: -x[1]["scans"]):
    hs = HUBSPOT.get(tenant, {})
    sdk_list = sorted(stats["sdkTypes"])
    detail_rows.append({
        "tenantName": tenant,
        "userId":     uid,
        "sdkTypes":   sdk_list,
        "sdkType":    ", ".join(sdk_list),
        "scans":      stats["scans"],
        "owner":      hs.get("owner", "—"),
        "se":         hs.get("se", "—"),
        "tam":        hs.get("tam", "—"),
        "is_internal": tenant in INTERNALS,
    })

# ── Account rows ───────────────────────────────────────────────────────────────
acct_agg = defaultdict(int)
for r in daily_90d:
    acct_agg[r["tenantName"]] += r["scans"]

account_rows = []
for tenant, total in sorted(acct_agg.items(), key=lambda x: -x[1]):
    hs = HUBSPOT.get(tenant, {})
    account_rows.append({
        "tenantName":    tenant,
        "total_scans":   total,
        "latest_scan":   latest_scan.get(tenant, "—"),
        "owner":         hs.get("owner", "—"),
        "se":            hs.get("se", "—"),
        "tam":           hs.get("tam", "—"),
        "tickets_month": hs.get("tickets_month", 0),
        "is_internal":   tenant in INTERNALS,
        "is_new":        hs.get("is_new", False),
        "renewal":       hs.get("renewal"),
    })

# ── Filter options ─────────────────────────────────────────────────────────────
tenant_opts   = "\n".join(f'<option value="{t}">{t}</option>' for t in sorted(set(r["tenantName"] for r in daily_90d if r["tenantName"])))
sdk_types_uniq = sorted(set(r["sdkType"] for r in daily_90d if r["sdkType"]))
sdk_type_opts = "\n".join(f'<option value="{s}">{s}</option>' for s in sdk_types_uniq)

# ── 90-day daily rows for JS ───────────────────────────────────────────────────
daily_rows = []
for r in daily_90d:
    if not r.get("date"):
        continue
    hs = HUBSPOT.get(r["tenantName"], {})
    daily_rows.append({
        "date":        r["date"],
        "tenantName":  r["tenantName"],
        "sdkType":     r["sdkType"],
        "platform":    r.get("platformName") or "",
        "scans":       r["scans"],
        "se":          hs.get("se", "—"),
        "owner":       hs.get("owner", "—"),
        "isInternal":  r["tenantName"] in INTERNALS,
    })

all_dates    = sorted(set(r["date"] for r in daily_90d if r.get("date")))
date_labels  = [_dt.strptime(d, "%Y-%m-%d").strftime("%b %d") for d in all_dates]

data_start = all_dates[0]  if all_dates else ""
data_end   = all_dates[-1] if all_dates else ""

# ── Raw per-day user rows for date-filterable detail table ────────────────────
raw_user_rows = []
for r in rows:
    uid = user_id(r) or ""
    hs = HUBSPOT.get(r["tenantName"], {})
    raw_user_rows.append({
        "tenantName":  r["tenantName"],
        "userId":      uid,
        "sdkType":     r["sdkType"],
        "date":        r.get("date") or "",
        "scans":       r["scans"],
        "se":          hs.get("se", "—"),
        "is_internal": r["tenantName"] in INTERNALS,
    })
raw_user_rows_js = json.dumps(raw_user_rows)

# ── JS blobs ───────────────────────────────────────────────────────────────────
detail_rows_js  = json.dumps(detail_rows)
account_rows_js = json.dumps(account_rows)
sdk_type_pie_js = json.dumps(SDK_TYPE_PIE)
sdk_tv_js       = json.dumps(SDK_TV_LIST)
daily_rows_js   = json.dumps(daily_rows)
date_keys_js    = json.dumps(all_dates)
date_labels_js  = json.dumps(date_labels)
internals_js       = json.dumps(list(INTERNALS))
sdk_product_js     = json.dumps(list(SDK_PRODUCT_TYPES))
zd_sev_labels_js   = json.dumps(ZD_SEV_LABELS)
zd_sev_values_js   = json.dumps(ZD_SEV_VALUES)
zd_type_labels_js  = json.dumps(ZD_TYPE_LABELS)
zd_type_values_js  = json.dumps(ZD_TYPE_VALUES)
zd_tickets_js      = json.dumps(ZD_TICKETS)
zd_total           = ZD_TOTAL
zd_is_real         = zendesk_severity is not None

# New and renewal tenants for highlights
new_tenants     = sorted(t for t, v in HUBSPOT.items() if v.get("is_new"))
renewal_tenants = sorted((t, v["renewal"]) for t, v in HUBSPOT.items() if v.get("renewal"))

# ── HTML ───────────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mobile Products Dashboard | Evinced</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
    :root {{
      --primary:#6D28D9; --bg:#F1F5F9; --card:#fff; --border:#E2E8F0;
      --text:#1E293B; --muted:#64748B; --faint:#94A3B8;
      --green:#10B981; --amber:#F59E0B; --red:#EF4444;
      --blue:#3B82F6; --indigo:#4F46E5; --teal:#0D9488;
    }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg); color:var(--text); font-size:13px; }}
    .header {{ background:linear-gradient(135deg,#3B0764,#6D28D9 60%,#7C3AED); color:#fff; padding:14px 24px; display:flex; align-items:center; justify-content:space-between; box-shadow:0 2px 10px rgba(0,0,0,.25); }}
    .header-left {{ display:flex; align-items:center; gap:14px; }}
    .header-icon {{ font-size:28px; }}
    .header-title {{ font-size:17px; font-weight:700; letter-spacing:-.3px; }}
    .header-sub {{ font-size:11px; opacity:.7; margin-top:1px; }}
    .pill {{ background:rgba(255,255,255,.15); border:1px solid rgba(255,255,255,.25); border-radius:20px; padding:4px 12px; font-size:11px; font-weight:500; }}
    .pill.green {{ background:rgba(16,185,129,.25); border-color:rgba(16,185,129,.4); }}
    .status-bar {{ background:#3B0764; padding:5px 24px; display:flex; justify-content:space-between; align-items:center; font-size:10px; color:rgba(255,255,255,.55); }}
    .status-bar-left {{ display:flex; gap:20px; }}
    .status-updated {{ font-size:10px; color:rgba(255,255,255,.45); }}
    .dot {{ display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
    .dot-live {{ background:#10B981; animation:pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
    .main {{ padding:18px 24px; max-width:1680px; margin:0 auto; }}
    .note-bar {{ background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; padding:8px 14px; margin-bottom:16px; font-size:11px; color:#1E40AF; }}
    .filters-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 18px; margin-bottom:18px; box-shadow:0 1px 4px rgba(0,0,0,.05); }}
    .filters-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
    .filters-label {{ font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; }}
    .btn-reset {{ font-size:11px; color:var(--primary); background:none; border:none; cursor:pointer; font-family:inherit; }}
    .filters-grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:10px; align-items:start; }}
    .fg label {{ display:block; font-size:10px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }}
    .fg select {{ width:100%; padding:6px 24px 6px 9px; border:1px solid var(--border); border-radius:6px; font-size:12px; color:var(--text); background:#FAFAFA; font-family:inherit; outline:none; appearance:none;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2394A3B8'/%3E%3C/svg%3E"); background-repeat:no-repeat; background-position:right 8px center; }}
    .fg select:focus {{ border-color:var(--primary); box-shadow:0 0 0 3px rgba(109,40,217,.1); }}
    /* Highlight card */
    .highlights-card {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:18px; }}
    .hl-panel {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; box-shadow:0 1px 4px rgba(0,0,0,.05); border-left:4px solid transparent; }}
    .hl-panel.hl-drop {{ border-left-color:var(--red); background:#FFF5F5; }}
    .hl-panel.hl-new  {{ border-left-color:var(--green); background:#F0FDF4; }}
    .hl-panel.hl-renew {{ border-left-color:var(--amber); background:#FFFBEB; }}
    .hl-title {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; margin-bottom:10px; }}
    .hl-drop .hl-title  {{ color:var(--red); }}
    .hl-new  .hl-title  {{ color:#065F46; }}
    .hl-renew .hl-title {{ color:#92400E; }}
    .hl-main {{ font-size:16px; font-weight:800; color:var(--text); margin-bottom:4px; }}
    .hl-sub  {{ font-size:11px; color:var(--muted); }}
    .hl-list {{ list-style:none; margin-top:6px; }}
    .hl-list li {{ font-size:11px; padding:3px 0; color:var(--text); border-bottom:1px solid rgba(0,0,0,.04); display:flex; align-items:center; gap:6px; }}
    .hl-list li:last-child {{ border-bottom:none; }}
    .kpi-row {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:18px; }}
    .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; box-shadow:0 1px 4px rgba(0,0,0,.05); position:relative; overflow:hidden; }}
    .kpi::after {{ content:''; position:absolute; top:0;left:0;right:0;height:3px; }}
    .kpi.c-purple::after {{ background:var(--primary); }} .kpi.c-blue::after {{ background:var(--blue); }}
    .kpi.c-teal::after   {{ background:var(--teal); }}   .kpi.c-indigo::after {{ background:var(--indigo); }}
    .kpi.c-green::after  {{ background:var(--green); }}  .kpi.c-violet::after {{ background:#7C3AED; }}
    .kpi-label {{ font-size:10px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:8px; }}
    .kpi-val {{ font-size:28px; font-weight:800; color:var(--text); line-height:1; margin-bottom:5px; letter-spacing:-.5px; }}
    .kpi-sub {{ font-size:10px; color:var(--faint); }}
    .charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:18px; }}
    .chart-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; box-shadow:0 1px 4px rgba(0,0,0,.05); }}
    .chart-header {{ display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:12px; }}
    .chart-title {{ font-size:13px; font-weight:600; }}
    .chart-source {{ font-size:9px; color:var(--faint); background:#F8FAFC; border:1px solid var(--border); padding:2px 7px; border-radius:8px; margin-top:2px; display:inline-block; }}
    .chart-wrap {{ height:170px; position:relative; }}
    .section-label {{ font-size:13px; font-weight:700; margin-bottom:10px; margin-top:4px; display:flex; align-items:center; gap:8px; }}
    .section-label span {{ font-size:10px; font-weight:500; color:var(--muted); }}
    .table-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; box-shadow:0 1px 4px rgba(0,0,0,.05); overflow:hidden; margin-bottom:18px; }}
    .table-header {{ display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid var(--border); }}
    .table-title {{ font-size:14px; font-weight:600; }}
    .table-controls {{ display:flex; align-items:center; gap:10px; }}
    .btn-export {{ padding:6px 14px; background:white; border:1px solid var(--border); border-radius:6px; font-size:11px; cursor:pointer; font-family:inherit; }}
    .table-scroll {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:11.5px; white-space:nowrap; }}
    thead th {{ background:#F8FAFC; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.4px; font-size:9.5px; padding:9px 12px; text-align:left; border-bottom:1px solid var(--border); cursor:pointer; user-select:none; }}
    thead th:hover {{ background:#EFF6FF; color:var(--primary); }}
    tbody tr {{ border-bottom:1px solid #F1F5F9; transition:background .1s; }}
    tbody tr:hover {{ filter:brightness(0.97); }}
    tbody tr:last-child {{ border-bottom:none; }}
    td {{ padding:9px 12px; }}
    td.mono {{ font-family:monospace; font-size:10px; color:var(--muted); }}
    td.num {{ font-variant-numeric:tabular-nums; font-weight:600; }}
    td.num-muted {{ font-variant-numeric:tabular-nums; color:var(--muted); }}
    .badge {{ display:inline-block; padding:2px 7px; border-radius:9px; font-size:10px; font-weight:600; }}
    .b-mfa {{ background:#EDE9FE; color:#5B21B6; }}
    .b-sdk {{ background:#DBEAFE; color:#1D4ED8; }}
    .b-new {{ background:#D1FAE5; color:#065F46; }}
    .b-renewal {{ background:#FEF3C7; color:#92400E; }}
    .b-int {{ background:#F1F5F9; color:#64748B; }}
    .b-drop {{ background:#FEE2E2; color:#991B1B; }}
    .b-none {{ color:#CBD5E1; font-size:12px; }}
    .row-new {{ background:#F0FDF4 !important; }}
    .row-renewal {{ background:#FFFBEB !important; }}
    .row-drop {{ background:#FFF1F2 !important; }}
    .legend-row {{ display:flex; gap:16px; padding:6px 18px 10px; font-size:10px; color:var(--muted); border-top:1px solid var(--border); }}
    .legend-dot {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:4px; vertical-align:middle; }}
    .table-footer {{ display:flex; align-items:center; justify-content:space-between; padding:10px 18px; border-top:1px solid var(--border); }}
    .page-info {{ font-size:11px; color:var(--muted); }}
    .pag {{ display:flex; align-items:center; gap:6px; }}
    .pag-btn {{ padding:5px 10px; border:1px solid var(--border); border-radius:5px; font-size:12px; cursor:pointer; background:white; font-family:inherit; }}
    .pag-btn:hover {{ background:#F8FAFC; }}
    .pag-btn:disabled {{ opacity:.4; cursor:default; }}
    .pag-pages {{ font-size:11px; color:var(--muted); min-width:80px; text-align:center; }}
    .zd-note {{ font-size:10px; color:var(--faint); font-style:italic; margin-top:6px; text-align:center; }}
    @media(max-width:1400px) {{ .kpi-row{{grid-template-columns:repeat(3,1fr)}} .charts-grid{{grid-template-columns:repeat(2,1fr)}} }}
    @media(max-width:900px)  {{ .filters-grid{{grid-template-columns:repeat(3,1fr)}} }}
  </style>
</head>
<body>
<header class="header">
  <div class="header-left">
    <div class="header-icon">📱</div>
    <div>
      <div class="header-title">Mobile Products Dashboard</div>
      <div class="header-sub">Mobile SDK · Mobile MFA &nbsp;·&nbsp; Usage · Adoption · Business Context</div>
    </div>
  </div>
  <div style="display:flex;gap:10px;align-items:center">
    <div class="pill">Evinced Analytics</div>
    <div class="pill green">● Live — BigQuery + HubSpot</div>
    <a href="/mobile-products-dashboard.pdf" target="_blank"
       style="background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);border-radius:20px;padding:4px 14px;font-size:11px;font-weight:500;color:#fff;text-decoration:none;white-space:nowrap;">
      ⬇ Export PDF
    </a>
    <button onclick="exportAllCSV()"
       style="background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);border-radius:20px;padding:4px 14px;font-size:11px;font-weight:500;color:#fff;cursor:pointer;font-family:inherit;white-space:nowrap;">
      ⬇ Export CSV
    </button>
  </div>
</header>
<div class="status-bar">
  <div class="status-bar-left">
    <span><span class="dot dot-live"></span>BigQuery: 90-day history · production</span>
    <span><span class="dot dot-live"></span>HubSpot: Owner / SE / TAM · tickets</span>
  </div>
  <span class="status-updated">Last updated: {LAST_UPDATED}</span>
</div>

<div class="main">
  <div class="note-bar">
    <strong>Data from BigQuery + HubSpot.</strong>&nbsp;
    <strong>{len(ext_tenants)} active external tenants</strong> ·
    <strong>{unique_users} active users</strong> ·
    <strong>{total_scans:,} scans (last 14d)</strong>.&nbsp;
    <span style="color:#1E40AF">🟢 New tenant</span> = HubSpot deal closed this month ·
    <span style="color:#92400E">🟡 Renewal</span> = deal ending Apr–May 2026 ·
    <span style="color:#991B1B">🔴 Drop</span> = biggest scan drop vs. prior period
  </div>

  <!-- FILTERS -->
  <div class="filters-card">
    <div class="filters-header">
      <span class="filters-label">⚙ Filters</span>
      <button class="btn-reset" onclick="resetFilters()">↺ Reset all</button>
    </div>
    <div class="filters-grid">
      <div class="fg"><label>Product</label>
        <select id="f-product" onchange="applyFilters()">
          <option value="all">All Products</option>
          <option value="mfa">Mobile MFA</option>
          <option value="sdk">Mobile SDK</option>
        </select></div>
      <div class="fg"><label>Tenant</label>
        <select id="f-tenant" onchange="applyFilters()">
          <option value="all">All Tenants</option>
          {tenant_opts}
        </select></div>
      <div class="fg"><label>SDK Type</label>
        <select id="f-sdk" onchange="applyFilters()">
          <option value="all">All Types</option>
          {sdk_type_opts}
        </select></div>
      <div class="fg"><label>Date Range</label>
        <select id="f-date" onchange="onDateChange()">
          <option value="30">Last 30 days</option>
          <option value="7">Last 7 days</option>
          <option value="60">Last 60 days</option>
          <option value="all">All data (90d)</option>
          <option value="custom">Custom range…</option>
        </select>
        <div id="custom-date-wrap" style="display:none;margin-top:5px;display:none;align-items:center;gap:4px">
          <input type="date" id="f-date-from" onchange="applyFilters()"
            style="padding:3px 5px;border:1px solid #E2E8F0;border-radius:5px;font-size:11px;color:#1E293B">
          <span style="color:#94A3B8;font-size:11px">–</span>
          <input type="date" id="f-date-to" onchange="applyFilters()"
            style="padding:3px 5px;border:1px solid #E2E8F0;border-radius:5px;font-size:11px;color:#1E293B">
        </div>
      </div>
      <div class="fg"><label>Show Internals</label>
        <select id="f-internals" onchange="applyFilters()">
          <option value="false">Hide Internals</option>
          <option value="true">Show Internals</option>
        </select></div>
      <div class="fg"><label>SE Owner</label>
        <select id="f-se" onchange="applyFilters()">
          <option value="all">All SEs</option>
        </select></div>
      <div class="fg"><label>Weekends</label>
        <select id="f-no-weekends" onchange="applyFilters()">
          <option value="include">Include weekends</option>
          <option value="exclude">Exclude weekends</option>
        </select></div>
    </div>
  </div>

  <!-- HIGHLIGHTS -->
  <div class="highlights-card">
    <div class="hl-panel hl-drop">
      <div class="hl-title">📉 Biggest Scan Drop vs. Prev Period</div>
      <div class="hl-main" id="hl-drop-tenant">—</div>
      <div class="hl-sub"  id="hl-drop-detail">Computed from selected date range</div>
    </div>
    <div class="hl-panel hl-new">
      <div class="hl-title">🟢 New &amp; Renewed Tenants</div>
      <ul class="hl-list" id="hl-new-list">
        {"".join(f"<li>✦ {t}</li>" for t in new_tenants) or "<li style='color:var(--faint)'>None this period</li>"}
      </ul>
      <div style="font-size:10px;color:var(--faint);margin-top:6px;font-style:italic">Tenants with a new or recently renewed HubSpot contract</div>
    </div>
    <div class="hl-panel hl-renew">
      <div class="hl-title">🟡 Upcoming Renewals</div>
      <ul class="hl-list" id="hl-renewal-list">
        {"".join(f'<li>⏱ <strong>{t}</strong> <span style="color:var(--faint);font-size:10px">· {d}</span></li>' for t, d in renewal_tenants) or "<li style='color:var(--faint)'>None upcoming</li>"}
      </ul>
    </div>
  </div>

  <!-- KPIs (6 cards — avg issues/scan and critical/scan removed) -->
  <div class="kpi-row">
    <div class="kpi c-blue">  <div class="kpi-label">Active Tenants</div><div class="kpi-val" id="k-tenants">{len(ext_tenants)}</div><div class="kpi-sub" id="k-tenants-sub">excl. internals</div></div>
    <div class="kpi c-teal">  <div class="kpi-label">Active Users</div><div class="kpi-val" id="k-users">{unique_users}</div><div class="kpi-sub">email (MFA) + service acct (SDK)</div></div>
    <div class="kpi c-indigo"><div class="kpi-label">Total Scans</div><div class="kpi-val" id="k-scans">{total_scans:,}</div><div class="kpi-sub" id="k-scans-sub">selected period</div></div>
    <div class="kpi c-green"> <div class="kpi-label">New Tenants</div><div class="kpi-val">{new_count}</div><div class="kpi-sub">MFA/Mobile deal · closed this month</div></div>
    <div class="kpi c-violet"><div class="kpi-label">Upcoming Renewals</div><div class="kpi-val">{renewal_count}</div><div class="kpi-sub">deal ending Apr–May 2026</div></div>
    <div class="kpi c-purple"><div class="kpi-label">Support Tickets</div><div class="kpi-val">{CURRENT_MONTH_TICKETS}</div><div class="kpi-sub">Zendesk · mobile/MFA · this month</div></div>
  </div>

  <!-- CHARTS: row 1 — Active Tenants · Total Scans · SDK Type Distribution -->
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Active Tenants Over Time</div><span class="chart-source">BigQuery · selected range</span></div></div>
      <div class="chart-wrap"><canvas id="ch-tenants"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Total Scans Over Time</div><span class="chart-source">BigQuery · selected range</span></div></div>
      <div class="chart-wrap"><canvas id="ch-scans"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">SDK Type Distribution</div><span class="chart-source">BigQuery · by scan count</span></div></div>
      <div class="chart-wrap"><canvas id="ch-sdk-type"></canvas></div>
    </div>
  </div>

  <!-- CHARTS: row 2 — Zendesk Severity · Zendesk by Product · SDK Type + Platform -->
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-header"><div>
        <div class="chart-title">Zendesk by Severity</div>
        <span class="chart-source" id="zd-sev-source">Zendesk · filtered by date</span>
      </div></div>
      <div class="chart-wrap"><canvas id="ch-zd-severity"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div>
        <div class="chart-title">Zendesk by Product Area</div>
        <span class="chart-source" id="zd-type-source">Zendesk · filtered by date</span>
      </div></div>
      <div class="chart-wrap"><canvas id="ch-tickets"></canvas></div>
    </div>
    <div class="chart-card" id="card-sdk-tv">
      <div class="chart-header"><div><div class="chart-title">SDK Type + Platform</div><span class="chart-source">BigQuery · os_name as variant</span></div></div>
      <div class="chart-wrap"><canvas id="ch-sdk-tv"></canvas></div>
    </div>
  </div>

  <!-- ACCOUNTS TABLE -->
  <div class="section-label">📋 Accounts <span>Tenant-level summary · sorted by total scans</span></div>
  <div class="table-card">
    <div class="table-header">
      <div class="table-title">Accounts Overview</div>
      <div class="table-controls"><button class="btn-export" onclick="exportAccounts()">⬇ Export CSV</button></div>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th onclick="sortAcct('tenantName')">Tenant ↕</th>
          <th onclick="sortAcct('total_scans')">Total Scans ↕</th>
          <th onclick="sortAcct('latest_scan')">Latest Scan ↕</th>
          <th>Contact Owner</th>
          <th>SE</th>
          <th>TAM</th>
          <th>Tags</th>
        </tr></thead>
        <tbody id="acct-body"></tbody>
      </table>
    </div>
    <div class="legend-row">
      <span><span class="legend-dot" style="background:#D1FAE5"></span>New tenant</span>
      <span><span class="legend-dot" style="background:#FEF3C7"></span>Upcoming renewal</span>
      <span><span class="legend-dot" style="background:#FEE2E2"></span>Biggest scan drop vs. prior period</span>
    </div>
    <div class="table-footer">
      <span class="page-info" id="acct-info"></span>
      <div class="pag">
        <button class="pag-btn" id="acct-prev" onclick="acctPrev()">← Prev</button>
        <span class="pag-pages" id="acct-pages"></span>
        <button class="pag-btn" id="acct-next" onclick="acctNext()">Next →</button>
      </div>
    </div>
  </div>

  <!-- USERS DETAIL TABLE -->
  <div class="section-label">👤 Users <span id="detail-range-label">Per-user scan detail · selected date range</span></div>
  <div class="table-card">
    <div class="table-header">
      <div class="table-title">User Scan Detail</div>
      <div class="table-controls"><button class="btn-export" onclick="exportDetail()">⬇ Export CSV</button></div>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th onclick="sortDet('tenantName')">Tenant ↕</th>
          <th onclick="sortDet('userId')">User ↕</th>
          <th onclick="sortDet('sdkType')">SDK Type ↕</th>
          <th onclick="sortDet('scans')">Scans ↕</th>
        </tr></thead>
        <tbody id="det-body"></tbody>
      </table>
    </div>
    <div class="table-footer">
      <span class="page-info" id="det-info"></span>
      <div class="pag">
        <button class="pag-btn" id="det-prev" onclick="detPrev()">← Prev</button>
        <span class="pag-pages" id="det-pages"></span>
        <button class="pag-btn" id="det-next" onclick="detNext()">Next →</button>
      </div>
    </div>
  </div>
</div>

<script>
// ── Constants ─────────────────────────────────────────────────────────────────
const DAILY_ROWS    = {daily_rows_js};
const DATE_KEYS     = {date_keys_js};
const DATE_LABELS   = {date_labels_js};
const SDK_TYPE_PIE  = {sdk_type_pie_js};
const SDK_TV_LIST   = {sdk_tv_js};
const DETAIL_ROWS   = {detail_rows_js};
const RAW_USER_ROWS = {raw_user_rows_js};
const ACCOUNT_ROWS  = {account_rows_js};
const INTERNALS        = new Set({internals_js});
const SDK_PRODUCTS     = new Set({sdk_product_js});
const ZD_TICKETS       = {zd_tickets_js};
const DATA_START       = {json.dumps(data_start)};
const DATA_END      = {json.dumps(data_end)};

const PER_PAGE = 10;

// ACCT_META for static HubSpot-sourced fields
const ACCT_META = {{}};
ACCOUNT_ROWS.forEach(r => {{ ACCT_META[r.tenantName] = r; }});

// ── Populate SE filter ────────────────────────────────────────────────────────
(function() {{
  const ses = [...new Set(ACCOUNT_ROWS.map(r => r.se).filter(s => s && s !== '—'))].sort();
  const sel = document.getElementById('f-se');
  ses.forEach(s => {{ const o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o); }});
}})();

// ── Date range setup ──────────────────────────────────────────────────────────
(function() {{
  const from = document.getElementById('f-date-from');
  const to   = document.getElementById('f-date-to');
  if (from && to) {{
    from.min = to.min = DATA_START;
    from.max = to.max = DATA_END;
    from.value = DATA_START;
    to.value   = DATA_END;
  }}
}})();

function onDateChange() {{
  const val  = document.getElementById('f-date').value;
  const wrap = document.getElementById('custom-date-wrap');
  wrap.style.display = val === 'custom' ? 'flex' : 'none';
  applyFilters();
}}

function isWeekend(dateStr) {{
  const d   = new Date(dateStr + 'T00:00:00');
  const day = d.getDay(); // 0=Sun, 6=Sat
  return day === 0 || day === 6;
}}

function zdFilteredTickets(startDate, endDate, noWeekends) {{
  return ZD_TICKETS.filter(t => {{
    if (!t.date || t.date < startDate || t.date > endDate) return false;
    if (noWeekends && isWeekend(t.date)) return false;
    return true;
  }});
}}

function updateZendeskCharts(startDate, endDate, noWeekends) {{
  const tickets = zdFilteredTickets(startDate, endDate, noWeekends);
  const total   = tickets.length;

  // Severity aggregation
  const sevAgg = {{}};
  tickets.forEach(t => {{ sevAgg[t.priority] = (sevAgg[t.priority]||0) + 1; }});
  const sevOrder = ['Normal','Low','High','Urgent','Critical'];
  const sevEntries = sevOrder.filter(k => sevAgg[k]).map(k => [k, sevAgg[k]]);
  // Also add any unexpected priorities
  Object.entries(sevAgg).forEach(([k,v]) => {{ if (!sevOrder.includes(k)) sevEntries.push([k,v]); }});

  // Type aggregation
  const typeAgg = {{}};
  tickets.forEach(t => {{ typeAgg[t.type] = (typeAgg[t.type]||0) + 1; }});

  const ZD_SEV_COLORS = {{'Normal':'#3B82F6','Low':'#10B981','High':'#F59E0B','Urgent':'#EF4444','Critical':'#DC2626'}};
  const ZD_TYPE_COLORS = ['#6D28D9','#3B82F6','#0D9488'];
  const CC2 = ['#6D28D9','#3B82F6','#0D9488','#F59E0B','#EF4444','#10B981'];

  if (CHARTS.zdSeverity) {{
    const labels = sevEntries.map(([k])=>k);
    const values = sevEntries.map(([,v])=>v);
    CHARTS.zdSeverity.data.labels   = labels;
    CHARTS.zdSeverity.data.datasets[0].data = values;
    CHARTS.zdSeverity.data.datasets[0].backgroundColor = labels.map(l=>(ZD_SEV_COLORS[l]||'#94A3B8')+'CC');
    CHARTS.zdSeverity.data.datasets[0].borderColor     = labels.map(l=> ZD_SEV_COLORS[l]||'#94A3B8');
    CHARTS.zdSeverity.update();
  }}
  if (CHARTS.tickets) {{
    const typeEntries = Object.entries(typeAgg).sort((a,b)=>b[1]-a[1]);
    CHARTS.tickets.data.labels = typeEntries.map(([k])=>k);
    CHARTS.tickets.data.datasets[0].data = typeEntries.map(([,v])=>v);
    CHARTS.tickets.data.datasets[0].backgroundColor = typeEntries.map((_,i)=>ZD_TYPE_COLORS[i%ZD_TYPE_COLORS.length]+'CC');
    CHARTS.tickets.data.datasets[0].borderColor     = typeEntries.map((_,i)=>ZD_TYPE_COLORS[i%ZD_TYPE_COLORS.length]);
    CHARTS.tickets.update();
  }}

  // Update source labels
  const src = `${{total}} tickets · ${{startDate}} – ${{endDate}}`;
  const sl = document.getElementById('zd-section-label'); if(sl) sl.textContent = 'mobile/MFA · ' + src;
  const ss = document.getElementById('zd-sev-source');   if(ss) ss.textContent = 'Zendesk · ' + src;
  const ts = document.getElementById('zd-type-source');  if(ts) ts.textContent = 'Zendesk · ' + src;
}}

function getDateRange() {{
  const val  = document.getElementById('f-date').value;
  const last = DATE_KEYS[DATE_KEYS.length - 1] || '';
  if (val === 'all')    return [DATE_KEYS[0] || '', last];
  if (val === 'custom') return [
    document.getElementById('f-date-from').value || DATE_KEYS[0] || '',
    document.getElementById('f-date-to').value   || last
  ];
  // Rolling: last N days from the latest date in data
  const days  = parseInt(val) || 30;
  const endDt = new Date(last + 'T00:00:00');
  const startDt = new Date(endDt);
  startDt.setDate(startDt.getDate() - days + 1);
  const start = startDt.toISOString().slice(0, 10);
  return [start, last];
}}

function getPrevDateRange(startDate, endDate) {{
  // Compute same-length window immediately before startDate
  const s = new Date(startDate + 'T00:00:00');
  const e = new Date(endDate   + 'T00:00:00');
  const len = Math.round((e - s) / 86400000) + 1;
  const prevEnd = new Date(s); prevEnd.setDate(prevEnd.getDate() - 1);
  const prevStart = new Date(prevEnd); prevStart.setDate(prevStart.getDate() - len + 1);
  return [prevStart.toISOString().slice(0,10), prevEnd.toISOString().slice(0,10)];
}}

// ── Chart colors ──────────────────────────────────────────────────────────────
const CC = ['#6D28D9','#3B82F6','#0D9488','#F59E0B','#EF4444','#10B981','#8B5CF6','#06B6D4'];
const CHARTS = {{}};

function mkLine(id, label, color, labels, data) {{
  return new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{ labels, datasets:[{{ label, data, borderColor:color, backgroundColor:color+'22', borderWidth:2, pointRadius:3, tension:0.3, fill:true }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend:{{display:false}}, tooltip:{{ backgroundColor:'#1E293B', bodyFont:{{size:11}}, padding:8, cornerRadius:6 }} }},
      scales: {{
        x: {{ grid:{{display:false}}, ticks:{{font:{{size:9}}, color:'#94A3B8', maxTicksLimit:12}} }},
        y: {{ grid:{{color:'#F1F5F9'}}, ticks:{{font:{{size:10}}, color:'#94A3B8'}}, beginAtZero:true }}
      }}
    }}
  }});
}}

function computeDaily(filteredRows, startDate, endDate) {{
  const keys   = DATE_KEYS.filter(d => d >= startDate && d <= endDate);
  const labels = keys.map(d => DATE_LABELS[DATE_KEYS.indexOf(d)] || d);
  const tMap = {{}}, sMap = {{}};
  filteredRows.forEach(r => {{
    if (r.date >= startDate && r.date <= endDate) {{
      if (!tMap[r.date]) tMap[r.date] = new Set();
      if (r.tenantName) tMap[r.date].add(r.tenantName);
      sMap[r.date] = (sMap[r.date] || 0) + (r.scans || 0);
    }}
  }});
  return {{
    labels,
    tenants: keys.map(d => tMap[d] ? tMap[d].size : 0),
    scans:   keys.map(d => sMap[d] || 0),
  }};
}}

function initCharts() {{
  const ext = DAILY_ROWS.filter(r => !r.isInternal);
  const [s, e] = getDateRange();
  const baseline = computeDaily(ext, s, e);

  CHARTS.tenants = mkLine('ch-tenants', 'Active Tenants', '#3B82F6', baseline.labels, baseline.tenants);
  CHARTS.scans   = mkLine('ch-scans',   'Total Scans',    '#6D28D9', baseline.labels, baseline.scans);

  // SDK type pie
  CHARTS.sdkType = new Chart(document.getElementById('ch-sdk-type'), {{
    type: 'pie',
    data: {{ labels: SDK_TYPE_PIE.map(s=>s.sdkType),
             datasets: [{{ data: SDK_TYPE_PIE.map(s=>s.scans),
               backgroundColor: SDK_TYPE_PIE.map((_,i)=>CC[i%CC.length]+'CC'),
               borderColor:     SDK_TYPE_PIE.map((_,i)=>CC[i%CC.length]), borderWidth:2 }}] }},
    options: {{ responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{position:'bottom',labels:{{font:{{size:9}},padding:8,boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed.toLocaleString()+' scans'}}}} }} }}
  }});

  // SDK type + platform bar
  CHARTS.sdkTV = new Chart(document.getElementById('ch-sdk-tv'), {{
    type: 'bar',
    data: {{ labels: SDK_TV_LIST.map(s=>s.label),
             datasets: [{{ data: SDK_TV_LIST.map(s=>s.scans),
               backgroundColor: SDK_TV_LIST.map((_,i)=>CC[i%CC.length]+'BB'),
               borderColor:     SDK_TV_LIST.map((_,i)=>CC[i%CC.length]), borderWidth:1 }}] }},
    options: {{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{display:false}}, tooltip:{{backgroundColor:'#1E293B',callbacks:{{label:ctx=>' '+ctx.parsed.x.toLocaleString()+' scans'}}}} }},
      scales: {{ x:{{grid:{{color:'#F1F5F9'}},ticks:{{font:{{size:9}},color:'#94A3B8'}},beginAtZero:true}},
                 y:{{grid:{{display:false}},ticks:{{font:{{size:9}},color:'#64748B'}}}} }} }}
  }});

  // Zendesk charts — initialized empty; applyFilters() will populate them with the correct date range
  const ZD_SEV_COLORS_INIT = {{'Normal':'#3B82F6','Low':'#10B981','High':'#F59E0B','Urgent':'#EF4444','Critical':'#DC2626'}};
  CHARTS.zdSeverity = new Chart(document.getElementById('ch-zd-severity'), {{
    type: 'pie',
    data: {{ labels: [], datasets: [{{ data: [], backgroundColor: [], borderColor: [], borderWidth: 2 }}] }},
    options: {{ responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{position:'bottom',labels:{{font:{{size:9}},padding:8,boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed+' ticket'+(ctx.parsed!==1?'s':'')}}}} }} }}
  }});
  CHARTS.tickets = new Chart(document.getElementById('ch-tickets'), {{
    type: 'doughnut',
    data: {{ labels: [], datasets: [{{ data: [], backgroundColor: [], borderColor: [], borderWidth: 2 }}] }},
    options: {{ responsive:true, maintainAspectRatio:false, cutout:'55%',
      plugins: {{ legend:{{position:'bottom',labels:{{font:{{size:9}},padding:8,boxWidth:10}}}},
        tooltip:{{backgroundColor:'#1E293B',callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed+' ticket'+(ctx.parsed!==1?'s':'')}}}} }} }}
  }});
}}

// ── State ─────────────────────────────────────────────────────────────────────
let detPage = 0, acctPage = 0;
let detSort  = {{key:'scans', dir:-1}};
let acctSort = {{key:'total_scans', dir:-1}};
let filteredDaily    = [...DAILY_ROWS];
let filteredDetail   = [...DETAIL_ROWS];
let filteredAccounts = [...ACCOUNT_ROWS];
let dropTenant = null; // tenant name with biggest scan drop

// ── Update charts ──────────────────────────────────────────────────────────────
function updateCharts() {{
  const [startDate, endDate] = getDateRange();

  // SDK type pie
  const sdkTypeAgg = {{}};
  filteredDaily.forEach(r => {{ sdkTypeAgg[r.sdkType] = (sdkTypeAgg[r.sdkType]||0) + r.scans; }});
  const sortedTypes = Object.entries(sdkTypeAgg).sort((a,b)=>b[1]-a[1]);
  CHARTS.sdkType.data.labels   = sortedTypes.map(([k])=>k);
  CHARTS.sdkType.data.datasets[0].data = sortedTypes.map(([,v])=>v);
  CHARTS.sdkType.data.datasets[0].backgroundColor = sortedTypes.map((_,i)=>CC[i%CC.length]+'CC');
  CHARTS.sdkType.data.datasets[0].borderColor = sortedTypes.map((_,i)=>CC[i%CC.length]);
  CHARTS.sdkType.update();

  // SDK type + platform bar
  const sdkTVAgg = {{}};
  filteredDaily.forEach(r => {{
    const key = r.sdkType + ' / ' + (r.platform||'—');
    sdkTVAgg[key] = (sdkTVAgg[key]||0) + r.scans;
  }});
  const sortedTV = Object.entries(sdkTVAgg).sort((a,b)=>b[1]-a[1]);
  CHARTS.sdkTV.data.labels = sortedTV.map(([k])=>k);
  CHARTS.sdkTV.data.datasets[0].data = sortedTV.map(([,v])=>v);
  CHARTS.sdkTV.data.datasets[0].backgroundColor = sortedTV.map((_,i)=>CC[i%CC.length]+'BB');
  CHARTS.sdkTV.data.datasets[0].borderColor = sortedTV.map((_,i)=>CC[i%CC.length]);
  CHARTS.sdkTV.update();

  // Line charts
  const daily = computeDaily(filteredDaily, startDate, endDate);
  CHARTS.tenants.data.labels = daily.labels;
  CHARTS.tenants.data.datasets[0].data = daily.tenants;
  CHARTS.scans.data.labels = daily.labels;
  CHARTS.scans.data.datasets[0].data = daily.scans;
  CHARTS.tenants.update();
  CHARTS.scans.update();
}}

// ── Apply filters ─────────────────────────────────────────────────────────────
function applyFilters() {{
  const product      = document.getElementById('f-product').value;
  const tenant       = document.getElementById('f-tenant').value;
  const sdk          = document.getElementById('f-sdk').value;
  const showInternal = document.getElementById('f-internals').value === 'true';
  const se           = document.getElementById('f-se').value;
  const noWeekends   = document.getElementById('f-no-weekends').value === 'exclude';
  const [startDate, endDate] = getDateRange();

  filteredDaily = DAILY_ROWS.filter(r => {{
    if (r.date < startDate || r.date > endDate) return false;
    if (noWeekends && isWeekend(r.date)) return false;
    if (!showInternal && r.isInternal) return false;
    if (tenant  !== 'all' && r.tenantName !== tenant) return false;
    if (sdk     !== 'all' && r.sdkType   !== sdk)    return false;
    if (product === 'mfa' && r.sdkType   !== 'MFA')  return false;
    if (product === 'sdk' && r.sdkType   === 'MFA')  return false;
    if (se !== 'all' && r.se !== se)                  return false;
    return true;
  }});

  // Compute previous-period rows for drop detection
  const [prevStart, prevEnd] = getPrevDateRange(startDate, endDate);
  const prevRows = DAILY_ROWS.filter(r => {{
    if (r.date < prevStart || r.date > prevEnd) return false;
    if (noWeekends && isWeekend(r.date)) return false;
    if (!showInternal && r.isInternal) return false;
    if (product === 'mfa' && r.sdkType !== 'MFA') return false;
    if (product === 'sdk' && r.sdkType === 'MFA') return false;
    return true;
  }});

  // Aggregate current and previous period scans by tenant
  const currScans = {{}}, prevScans = {{}};
  filteredDaily.forEach(r => {{ currScans[r.tenantName] = (currScans[r.tenantName]||0) + r.scans; }});
  prevRows.forEach(r => {{  prevScans[r.tenantName] = (prevScans[r.tenantName]||0) + r.scans; }});

  // Find tenant with biggest % drop (only where prev > 0 and has current data)
  let biggestDrop = 0; dropTenant = null;
  Object.keys(currScans).forEach(name => {{
    if (INTERNALS.has(name)) return;
    const cur  = currScans[name] || 0;
    const prev = prevScans[name] || 0;
    if (prev > 100) {{ // only meaningful if previously had significant activity
      const drop = (prev - cur) / prev;
      if (drop > biggestDrop) {{ biggestDrop = drop; dropTenant = name; }}
    }}
  }});

  // Re-aggregate account rows from filteredDaily
  const acctMap = {{}};
  filteredDaily.forEach(r => {{
    if (!acctMap[r.tenantName]) {{
      const m = ACCT_META[r.tenantName] || {{}};
      acctMap[r.tenantName] = {{
        tenantName:    r.tenantName,
        total_scans:   0,
        latest_scan:   m.latest_scan   || '—',
        owner:         r.owner         || '—',
        se:            r.se            || '—',
        tam:           (m.tam)         || '—',
        tickets_month: m.tickets_month || 0,
        is_internal:   r.isInternal,
        is_new:        m.is_new        || false,
        renewal:       m.renewal       || null,
        prev_scans:    prevScans[r.tenantName] || 0,
      }};
    }}
    acctMap[r.tenantName].total_scans += r.scans;
  }});
  filteredAccounts = Object.values(acctMap);

  // Detail table: aggregate RAW_USER_ROWS filtered by all active filters incl. date
  const rawFiltered = RAW_USER_ROWS.filter(r => {{
    if (!r.date || r.date < startDate || r.date > endDate) return false;
    if (noWeekends && isWeekend(r.date)) return false;
    if (!showInternal && r.is_internal) return false;
    if (tenant  !== 'all' && r.tenantName !== tenant) return false;
    if (product === 'mfa' && r.sdkType    !== 'MFA')  return false;
    if (product === 'sdk' && r.sdkType    === 'MFA')  return false;
    if (sdk     !== 'all' && r.sdkType    !== sdk)    return false;
    if (se      !== 'all' && r.se         !== se)     return false;
    return true;
  }});
  const detMap = {{}};
  rawFiltered.forEach(r => {{
    const key = r.tenantName + '|||' + r.userId;
    if (!detMap[key]) {{
      detMap[key] = {{ tenantName: r.tenantName, userId: r.userId, sdkTypesSet: new Set(), scans: 0, se: r.se, is_internal: r.is_internal }};
    }}
    detMap[key].sdkTypesSet.add(r.sdkType);
    detMap[key].scans += r.scans;
  }});
  filteredDetail = Object.values(detMap).map(r => {{
    const types = [...r.sdkTypesSet].sort();
    return {{ tenantName: r.tenantName, userId: r.userId, sdkTypes: types, sdkType: types.join(', '), scans: r.scans, se: r.se, is_internal: r.is_internal }};
  }});

  // Hide SDK Type + Platform chart when filtering on MFA only
  const sdkTvCard = document.getElementById('card-sdk-tv');
  if (sdkTvCard) sdkTvCard.style.display = (product === 'mfa') ? 'none' : '';

  detPage = 0; acctPage = 0;
  updateKPIs(startDate, endDate);
  updateCharts();
  updateZendeskCharts(startDate, endDate, noWeekends);
  updateHighlights(startDate, endDate);
  renderAccounts();
  renderDetail();
}}

function resetFilters() {{
  ['f-product','f-tenant','f-sdk','f-date','f-internals','f-se','f-no-weekends'].forEach(id => {{
    const el = document.getElementById(id); if (el) el.selectedIndex = 0;
  }});
  const wrap = document.getElementById('custom-date-wrap');
  if (wrap) wrap.style.display = 'none';
  document.getElementById('f-date-from').value = DATA_START;
  document.getElementById('f-date-to').value   = DATA_END;
  applyFilters();
}}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function updateKPIs(startDate, endDate) {{
  const tenantSet = {{}};
  let scans = 0;
  filteredDaily.forEach(r => {{
    if (!r.isInternal) tenantSet[r.tenantName] = 1;
    scans += r.scans;
  }});
  const userSet = new Set(filteredDetail.filter(r => r.userId).map(r => r.userId));
  document.getElementById('k-tenants').textContent = Object.keys(tenantSet).length;
  document.getElementById('k-users').textContent   = userSet.size;
  document.getElementById('k-scans').textContent   = scans.toLocaleString();

  const rangeLabel = startDate + ' – ' + endDate;
  const sub1 = document.getElementById('k-tenants-sub');
  const sub2 = document.getElementById('k-scans-sub');
  const sub3 = document.getElementById('detail-range-label');
  if (sub1) sub1.textContent = rangeLabel + ' · excl. internals';
  if (sub2) sub2.textContent = rangeLabel;
  if (sub3) sub3.textContent = 'Per-user scan detail · ' + rangeLabel;
}}

// ── Highlights — biggest drop ─────────────────────────────────────────────────
function updateHighlights(startDate, endDate) {{
  const tenantEl  = document.getElementById('hl-drop-tenant');
  const detailEl  = document.getElementById('hl-drop-detail');
  if (!tenantEl) return;

  if (!dropTenant) {{
    tenantEl.textContent = '—';
    detailEl.textContent = 'No significant drop detected in this period';
    return;
  }}

  // Find the drop details from filteredAccounts
  const acct = filteredAccounts.find(a => a.tenantName === dropTenant);
  if (!acct) {{ tenantEl.textContent = dropTenant; detailEl.textContent = ''; return; }}

  const prev = acct.prev_scans || 0;
  const curr = acct.total_scans || 0;
  const pct  = prev > 0 ? Math.round((prev - curr) / prev * 100) : 0;
  tenantEl.textContent = dropTenant;
  detailEl.textContent = curr.toLocaleString() + ' scans vs. ' + prev.toLocaleString() + ' prev period (−' + pct + '%)';
}}

// ── Render helpers ────────────────────────────────────────────────────────────
function dash(v) {{
  return (v && v !== '—') ? v : '<span class="b-none">—</span>';
}}

// ── Accounts table ────────────────────────────────────────────────────────────
function sortAcct(key) {{
  if (acctSort.key===key) acctSort.dir*=-1; else {{ acctSort.key=key; acctSort.dir=-1; }}
  acctPage = 0; renderAccounts();
}}
function acctPrev() {{ if (acctPage>0) {{ acctPage--; renderAccounts(); }} }}
function acctNext() {{
  const pages = Math.ceil(filteredAccounts.length/PER_PAGE);
  if (acctPage < pages-1) {{ acctPage++; renderAccounts(); }}
}}

function renderAccounts() {{
  const sorted = [...filteredAccounts].sort((a,b) => {{
    const av=a[acctSort.key]??'', bv=b[acctSort.key]??'';
    return typeof av==='number' ? (av-bv)*acctSort.dir : String(av).localeCompare(String(bv))*acctSort.dir;
  }});
  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total/PER_PAGE));
  acctPage = Math.min(acctPage, pages-1);
  const page = sorted.slice(acctPage*PER_PAGE, (acctPage+1)*PER_PAGE);

  document.getElementById('acct-body').innerHTML = page.map(r => {{
    const isDrop = r.tenantName === dropTenant && !r.is_new;
    const rowClass = r.is_new ? 'row-new' : (r.renewal ? 'row-renewal' : (isDrop ? 'row-drop' : ''));

    // Calculate scan delta vs prev period
    let deltaHtml = '';
    if (r.prev_scans > 0) {{
      const pct = Math.round((r.total_scans - r.prev_scans) / r.prev_scans * 100);
      const sign = pct >= 0 ? '+' : '';
      const color = pct >= 0 ? 'var(--green)' : 'var(--red)';
      deltaHtml = `<span style="font-size:10px;color:${{color}};margin-left:6px">${{sign}}${{pct}}%</span>`;
    }}

    return `<tr class="${{rowClass}}">
      <td><strong>${{r.tenantName}}</strong>${{isDrop ? ' <span class="badge b-drop" title="Biggest drop vs prior period">↓ Drop</span>' : ''}}</td>
      <td class="num">${{r.total_scans.toLocaleString()}}${{deltaHtml}}</td>
      <td style="color:var(--muted);font-size:11px">${{r.latest_scan||'—'}}</td>
      <td>${{dash(r.owner)}}</td>
      <td>${{dash(r.se)}}</td>
      <td>${{dash(r.tam)}}</td>
      <td>
        ${{r.is_new    ? '<span class="badge b-new">New</span> '      : ''}}
        ${{r.renewal   ? '<span class="badge b-renewal">Renewal</span> ' : ''}}
        ${{r.is_internal? '<span class="badge b-int">Internal</span>' : ''}}
      </td>
    </tr>`;
  }}).join('');

  document.getElementById('acct-info').textContent = total + ' account' + (total!==1?'s':'');
  document.getElementById('acct-pages').textContent = 'Page ' + (acctPage+1) + ' / ' + pages;
  document.getElementById('acct-prev').disabled = acctPage === 0;
  document.getElementById('acct-next').disabled = acctPage >= pages-1;
}}

// ── Detail table ──────────────────────────────────────────────────────────────
function sortDet(key) {{
  if (detSort.key===key) detSort.dir*=-1; else {{ detSort.key=key; detSort.dir=-1; }}
  detPage = 0; renderDetail();
}}
function detPrev() {{ if (detPage>0) {{ detPage--; renderDetail(); }} }}
function detNext() {{
  const pages = Math.ceil(filteredDetail.length/PER_PAGE);
  if (detPage < pages-1) {{ detPage++; renderDetail(); }}
}}

function renderDetail() {{
  const sorted = [...filteredDetail].sort((a,b) => {{
    const av=a[detSort.key]??'', bv=b[detSort.key]??'';
    return typeof av==='number' ? (av-bv)*detSort.dir : String(av).localeCompare(String(bv))*detSort.dir;
  }});
  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total/PER_PAGE));
  detPage = Math.min(detPage, pages-1);
  const page = sorted.slice(detPage*PER_PAGE, (detPage+1)*PER_PAGE);

  document.getElementById('det-body').innerHTML = page.map(r => `
    <tr>
      <td><strong>${{r.tenantName}}</strong></td>
      <td class="mono">${{r.userId || '<span class="b-none">—</span>'}}</td>
      <td>${{r.sdkTypes.map(t=>'<span class="badge '+(t==='MFA'?'b-mfa':'b-sdk')+'">'+t+'</span>').join(' ')}}</td>
      <td class="num">${{r.scans.toLocaleString()}}</td>
    </tr>`).join('');

  document.getElementById('det-info').textContent = total + ' row' + (total!==1?'s':'');
  document.getElementById('det-pages').textContent = 'Page ' + (detPage+1) + ' / ' + pages;
  document.getElementById('det-prev').disabled = detPage === 0;
  document.getElementById('det-next').disabled = detPage >= pages-1;
}}

// ── Export ────────────────────────────────────────────────────────────────────
function exportAllCSV() {{
  // Exports the currently-filtered accounts table as a full CSV
  const h = ['Tenant','Total Scans','Latest Scan','Contact Owner','SE','TAM','New','Renewal','Prev Period Scans'];
  const d = filteredAccounts.map(r => [
    r.tenantName, r.total_scans, r.latest_scan||'—', r.owner, r.se, r.tam,
    r.is_new?'Yes':'', r.renewal||'', r.prev_scans||0
  ]);
  const a = document.createElement('a');
  a.href = 'data:text/csv,' + encodeURIComponent(toCSV(h, d));
  a.download = 'evinced-mobile-dashboard-' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
}}

function toCSV(headers, rows) {{
  const esc = v => '"' + String(v??'').replace(/"/g,'""') + '"';
  return [headers.map(esc).join(','), ...rows.map(r=>r.map(esc).join(','))].join('\\n');
}}
function exportAccounts() {{
  const h = ['Tenant','Total Scans','Latest Scan','Contact Owner','SE','TAM','New','Renewal'];
  const d = filteredAccounts.map(r=>[r.tenantName,r.total_scans,r.latest_scan,r.owner,r.se,r.tam,r.is_new?'Yes':'',r.renewal||'']);
  const a = document.createElement('a'); a.href='data:text/csv,'+encodeURIComponent(toCSV(h,d));
  a.download='accounts_'+new Date().toISOString().slice(0,10)+'.csv'; a.click();
}}
function exportDetail() {{
  const h = ['Tenant','User','SDK Types','Scans'];
  const d = filteredDetail.map(r=>[r.tenantName,r.userId,r.sdkType,r.scans]);
  const a = document.createElement('a'); a.href='data:text/csv,'+encodeURIComponent(toCSV(h,d));
  a.download='users_'+new Date().toISOString().slice(0,10)+'.csv'; a.click();
}}

// ── Boot ──────────────────────────────────────────────────────────────────────
initCharts();
applyFilters();
</script>
</body>
</html>"""

OUTPUT_DIR_ENV = os.environ.get("OUTPUT_DIR") or BASE
os.makedirs(OUTPUT_DIR_ENV, exist_ok=True)
out_path = os.path.join(OUTPUT_DIR_ENV, "mobile-products-dashboard.html")
with open(out_path, "w") as f:
    f.write(html)

print(f"Written: {out_path}  ({len(html):,} chars)")
print(f"SDK types: {[s['sdkType'] for s in SDK_TYPE_PIE]}")
print(f"SDK type+platform combos: {len(SDK_TV_LIST)}")
print(f"Daily rows: {len(daily_rows)}, date range: {data_start} → {data_end}")
print(f"Account rows: {len(account_rows)}, Detail rows: {len(detail_rows)}")
