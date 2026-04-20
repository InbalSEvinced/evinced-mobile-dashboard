#!/usr/bin/env python3
"""
Mobile Products Dashboard v5 — fixes on top of v4:
v4 fixes (preserved):
  1. SDK type normalization (ESPRESSO_SDK→Espresso etc.)
  2. Product filter classifies MFA vs SDK correctly
  3. SDK Type + Variant chart
  4-5. sdkType / sdkVariant normalization
  6. Accounts table: no Active Users column
  7. Latest scan: real date from Coralogix
  8. Users table rendering confirmed
  9. 10 rows/page with prev/next arrows

v5 fixes:
  A. Users table: removed Contact Owner, SE, TAM columns (and from CSV export)
  B. Charts (SDK pie + SDK type+variant bar) now update dynamically on filter change
  C. Accounts table now applies product AND SDK type filters
"""
import json, csv, os
from collections import defaultdict

BASE    = os.path.dirname(os.path.abspath(__file__))
OUTPUTS = os.environ.get("OUTPUT_DIR") or os.path.join(BASE, "output")
os.makedirs(OUTPUTS, exist_ok=True)

# ── Load data ──────────────────────────────────────────────────────────────────
rows        = json.load(open(os.path.join(BASE, "rows_with_sa.json")))
# timeseries_new.json is not produced by any script in this repo; the TIMESERIES
# JS constant it feeds is declared but unused. Default to {} when absent.
_ts_path = os.path.join(BASE, "timeseries_new.json")
timeseries  = json.load(open(_ts_path)) if os.path.exists(_ts_path) else {}
latest_scan = json.load(open(os.path.join(BASE, "latest_scan_dates.json")))

# ── Pendo MFA feature events (CSV) ────────────────────────────────────────────
PENDO_FOCUS_CATS = ["Scan", "Connection", "Report"]
_pendo_raw = []
_pendo_path = os.path.join(BASE, "mfa_events.csv")
if not os.path.exists(_pendo_path):
    # fallback: check uploads folder in parent mnt directory
    _pendo_path = os.path.join(OUTPUTS, "..", "uploads", "mfa_events.csv")
with open(_pendo_path) as f:
    for row in csv.DictReader(f):
        events = int(row["Events (30d)"])
        if events > 0 and row["Category"] in PENDO_FOCUS_CATS:
            label = row["Feature Name"].replace("MFA - ", "").replace("MFA ", "")
            _pendo_raw.append({
                "feature":  label[:40],   # truncate long names for chart labels
                "category": row["Category"],
                "events":   events,
                "visitors": int(row["Visitors (30d)"]),
            })

# Per-category aggregates
pendo_cat = {}
for cat in PENDO_FOCUS_CATS:
    feats = sorted([r for r in _pendo_raw if r["category"] == cat], key=lambda x: -x["events"])
    pendo_cat[cat] = {
        "users":    max((r["visitors"] for r in feats), default=0),  # max visitors = conservative unique-user estimate
        "events":   sum(r["events"] for r in feats),
        "features": feats,
    }

# ── SDK type normalization ─────────────────────────────────────────────────────
# Maps raw Coralogix sdkType values to clean display names
SDK_TYPE_NORM = {
    # MFA
    "MFA": "MFA", "mfa": "MFA",
    "mobileflowanalyzer": "MFA", "mobile_flow_analyzer": "MFA",
    # Espresso (Android)
    "ESPRESSO_SDK": "Espresso", "espresso_sdk": "Espresso", "espresso": "Espresso",
    # WebdriverIO
    "WDIO_MOBILE_SDK": "WebdriverIO", "wdio_mobile_sdk": "WebdriverIO", "wdio": "WebdriverIO",
    # XCUITest (iOS) — two variants exist in the data
    "XCUISDK": "XCUITest", "xcuisdk": "XCUITest",
    "XCUI_SDK": "XCUITest", "xcui_sdk": "XCUITest",
    # Appium — Java and Python grouped together
    "APPIUM_JAVA_SDK": "Appium", "appium_java_sdk": "Appium",
    "APPIUM_PYTHON_SDK": "Appium", "appium_python_sdk": "Appium",
    "appium": "Appium",
    # MCP Server
    "MCP_SERVER_MOBILE": "MCP Server", "mcp_server_mobile": "MCP Server",
}

# ── SDK variant normalization ──────────────────────────────────────────────────
SDK_VARIANT_NORM = {
    "UiAutomator2": "UIAutomator2",
    "uiautomator2": "UIAutomator2",
    "UIAutomator2": "UIAutomator2",
    "XCUITest": "XCUITest",
    "Android": "Android",
    "iOS": "iOS",
}

# SDK types that count as "Mobile SDK" (not MFA)
SDK_PRODUCT_TYPES = {"Espresso", "WebdriverIO", "XCUITest", "Appium", "MCP Server"}

def norm_sdk_type(s):
    if not s: return "Unknown"
    return SDK_TYPE_NORM.get(s.strip()) or SDK_TYPE_NORM.get(s.strip().lower()) or s.strip()

def norm_sdk_variant(v):
    if not v or str(v).lower() in ("null", "none", ""): return None
    return SDK_VARIANT_NORM.get(str(v).strip()) or str(v).strip()

for r in rows:
    r["sdkType"]    = norm_sdk_type(r.get("sdkType", ""))
    r["sdkVariant"] = norm_sdk_variant(r.get("sdkVariant"))

# ── Internals ─────────────────────────────────────────────────────────────────
INTERNALS = {"Evinced Demo Account", "Evinced Dev Team", "GD", "Evinced Support"}

# ── HubSpot + Zendesk data (loaded from fetch_hubspot.py / fetch_zendesk.py) ──
def _load_account_metadata():
    """Merge HubSpot and Zendesk data. Falls back to hardcoded defaults if files missing."""
    hs_path = os.path.join(BASE, "hubspot_accounts.json")
    zd_path = os.path.join(BASE, "zendesk_tickets.json")

    hs = json.load(open(hs_path)) if os.path.exists(hs_path) else {}
    zd = json.load(open(zd_path)) if os.path.exists(zd_path) else {}

    if not hs:
        print("⚠  hubspot_accounts.json not found — using fallback data. Run fetch_hubspot.py to populate.")
    if not zd:
        print("⚠  zendesk_tickets.json not found — ticket counts will show 0. Run fetch_zendesk.py to populate.")

    # Merge: for every tenant seen in either source, combine fields
    all_keys = set(hs.keys()) | set(zd.keys())
    merged = {}
    for k in all_keys:
        h = hs.get(k, {})
        z = zd.get(k, {})
        merged[k] = {
            "owner":         h.get("owner", "—"),
            "se":            h.get("se", "—"),
            "tam":           h.get("tam", "—"),
            "renewal":       h.get("renewal", None),
            "is_new":        h.get("is_new", False),
            "tickets_all":   z.get("tickets_all", 0),
            "tickets_month": z.get("tickets_month", 0),
        }
    return merged

HUBSPOT = _load_account_metadata()

# ── Hardcoded fallback (used only if hubspot_accounts.json is missing) ─────────
_FALLBACK = {
    "Amazon Blink":         {"owner": "—",               "se": "Dominic Lucia",    "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 2,  "tickets_month": 0},
    "American Airlines":    {"owner": "Jacob Hume",      "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0},
    "Auticon":              {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "—",             "is_new": False, "renewal": "2026-05-31", "tickets_all": 1,  "tickets_month": 0},
    "BECU":                 {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0},
    "Bank of Ireland":      {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0},
    "Bell Media":           {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 1},
    "Booking":              {"owner": "Liam Ingleby",    "se": "Kevin Berg",       "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0},
    "Canal Plus":           {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Capital One":          {"owner": "Navin Thadani",   "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 4,  "tickets_month": 0},
    "Charter":              {"owner": "—",               "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Chewy":                {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Cigna":                {"owner": "Skye Hollins",    "se": "Justin Schaeffer", "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 5,  "tickets_month": 0},
    "Collective Health":    {"owner": "—",               "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Comcast":              {"owner": "Jacob Hume",      "se": "Kevin Berg",       "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Costco":               {"owner": "—",               "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "CreditOne":            {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Evinced Demo Account": {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Evinced Dev Team":     {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Evinced Support":      {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Expedia Group":        {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": True,  "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Fidelity Investments": {"owner": "—",               "se": "Dominic Lucia",    "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 4,  "tickets_month": 0},
    "GD":                   {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "HCAHealthcare":        {"owner": "—",               "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Huntington Bank":      {"owner": "Skye Hollins",    "se": "Kevin Berg",       "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Hyatt":                {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Lufthansa":            {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Maximus":              {"owner": "Amandeep Dhillon","se": "Justin Schaeffer", "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Microsoft":            {"owner": "Ryan Patterson",  "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "NatWest":              {"owner": "Liam Ingleby",    "se": "Chris Keene",      "tam": "Roei Ben Haim", "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "PCCW":                 {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 1},
    "Pinterest":            {"owner": "—",               "se": "Justin Schaeffer", "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Progressive":          {"owner": "Jacob Hume",      "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "SAP":                  {"owner": "Sam O'Meara",     "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 0},
    "Sainsburys":           {"owner": "Julian Miller",   "se": "Chris Keene",      "tam": "Gilad Aziza",   "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
    "Sky UK":               {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 3,  "tickets_month": 0},
    "Subway":               {"owner": "Skye Hollins",    "se": "David Martin",     "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 1,  "tickets_month": 1},
    "TakeHomeTests":        {"owner": "—",               "se": "—",                "tam": "—",             "is_new": False, "renewal": None,         "tickets_all": 0,  "tickets_month": 0},
}
if not HUBSPOT:
    HUBSPOT = _FALLBACK

CURRENT_MONTH_TICKETS = sum(v.get("tickets_month", 0) for v in HUBSPOT.values())

# ── Derived summaries ──────────────────────────────────────────────────────────
def user_id(r): return r.get("email") or r.get("serviceAccountId") or None

all_tenants    = sorted(set(r["tenantName"] for r in rows if r["tenantName"]))
ext_tenants    = [t for t in all_tenants if t not in INTERNALS]
sdk_types_uniq = sorted(set(r["sdkType"] for r in rows if r["sdkType"]))
total_scans    = sum(r["scans"] for r in rows)
unique_users   = len(set(user_id(r) for r in rows if user_id(r)))
new_count      = sum(1 for v in HUBSPOT.values() if v["is_new"])
renewal_count  = sum(1 for v in HUBSPOT.values() if v["renewal"])

# ── SDK pie — type only ───────────────────────────────────────────────────────
sdk_type_agg = defaultdict(int)
for r in rows:
    sdk_type_agg[r["sdkType"]] += r["scans"]
SDK_TYPE_PIE = [{"sdkType": k, "scans": v} for k, v in sorted(sdk_type_agg.items(), key=lambda x: -x[1])]

# ── SDK type+variant stacked bar ──────────────────────────────────────────────
sdk_tv_agg = defaultdict(int)
for r in rows:
    variant = r.get("sdkVariant") or "—"
    key = f"{r['sdkType']} / {variant}"
    sdk_tv_agg[key] += r["scans"]
SDK_TV_LIST = [{"label": k, "scans": v} for k, v in sorted(sdk_tv_agg.items(), key=lambda x: -x[1]) if v > 0]

# ── Detail rows: group by (tenant, userId) — no sdkType so cross-product users don't duplicate ──
det_agg = defaultdict(lambda: {"scans": 0, "total_issues": 0, "critical_issues": 0, "sdkTypes": set()})
for r in rows:
    uid = user_id(r) or ""
    key = (r["tenantName"], uid)
    det_agg[key]["scans"]           += r["scans"]
    det_agg[key]["total_issues"]    += r["total_issues"]
    det_agg[key]["critical_issues"] += r["critical_issues"]
    det_agg[key]["sdkTypes"].add(r["sdkType"])

detail_rows = []
for (tenant, uid), stats in sorted(det_agg.items(), key=lambda x: -x[1]["scans"]):
    hs = HUBSPOT.get(tenant, {})
    sdk_list = sorted(stats["sdkTypes"])
    detail_rows.append({
        "tenantName":      tenant,
        "userId":          uid,
        "sdkTypes":        sdk_list,                        # array — used for JS filtering
        "sdkType":         ", ".join(sdk_list),             # display string
        "scans":           stats["scans"],
        "total_issues":    stats["total_issues"],
        "critical_issues": stats["critical_issues"],
        "owner":           hs.get("owner", "—"),
        "se":              hs.get("se", "—"),
        "tam":             hs.get("tam", "—"),
        "is_internal":     tenant in INTERNALS,
    })

# ── Accounts table ─────────────────────────────────────────────────────────────
acct_agg = defaultdict(lambda: {"scans": 0})
for r in rows:
    acct_agg[r["tenantName"]]["scans"] += r["scans"]

account_rows = []
for tenant, stats in sorted(acct_agg.items(), key=lambda x: -x[1]["scans"]):
    hs = HUBSPOT.get(tenant, {})
    account_rows.append({
        "tenantName":    tenant,
        "total_scans":   stats["scans"],
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
tenant_opts   = "\n".join(f'<option value="{t}">{t}</option>' for t in all_tenants)
sdk_type_opts = "\n".join(f'<option value="{s}">{s}</option>' for s in sdk_types_uniq)

# ── Daily rows for chart + table filtering ────────────────────────────────────
# Each entry carries everything needed to re-aggregate tables + KPIs on the fly in JS.
daily_rows = []
for r in rows:
    if not r.get("date"):
        continue
    uid = user_id(r) or None
    hs  = HUBSPOT.get(r["tenantName"], {})
    daily_rows.append({
        "date":           r["date"],
        "tenantName":     r["tenantName"],
        "userId":         uid,
        "sdkType":        r["sdkType"],
        "sdkVariant":     r.get("sdkVariant"),
        "scans":          r["scans"],
        "total_issues":   r["total_issues"],
        "critical_issues": r["critical_issues"],
        "se":             hs.get("se", "—"),
        "owner":          hs.get("owner", "—"),
        "tam":            hs.get("tam", "—"),
        "isInternal":     r["tenantName"] in INTERNALS,
    })

# Build ordered date labels from the data itself
from datetime import datetime as _dt
all_dates = sorted(set(r["date"] for r in rows if r.get("date")))
date_labels = [_dt.strptime(d, "%Y-%m-%d").strftime("%b %d") for d in all_dates]

# ── Date range labels ──────────────────────────────────────────────────────────
from datetime import timedelta as _td

# Coralogix window: actual dates in the data
if all_dates:
    cx_start = _dt.strptime(all_dates[0],  "%Y-%m-%d")
    cx_end   = _dt.strptime(all_dates[-1], "%Y-%m-%d")
    coralogix_date_range = f"{cx_start.strftime('%b')} {cx_start.day} – {cx_end.strftime('%b')} {cx_end.day}, {cx_end.year}"
else:
    coralogix_date_range = "Apr 2026"

# Pendo window: April 2026 month-to-date export (Apr 1 – Apr 16, 2026)
pendo_date_range = "Apr 1 – Apr 16, 2026"

# Calendar-week options derived from available dates
_week_bounds = {}
for _d in all_dates:
    _dt_obj = _dt.strptime(_d, "%Y-%m-%d")
    _monday = (_dt_obj - _td(days=_dt_obj.weekday())).strftime("%Y-%m-%d")
    if _monday not in _week_bounds:
        _week_bounds[_monday] = {"start": _d, "end": _d}
    else:
        _week_bounds[_monday]["end"] = _d

week_options = []
for _wk in sorted(_week_bounds):
    _b = _week_bounds[_wk]
    _s = _dt.strptime(_b["start"], "%Y-%m-%d")
    _e = _dt.strptime(_b["end"],   "%Y-%m-%d")
    week_options.append({
        "label": f"{_s.strftime('%b')} {_s.day} – {_e.strftime('%b')} {_e.day}",
        "start": _b["start"],
        "end":   _b["end"],
    })

data_start = all_dates[0]  if all_dates else ""
data_end   = all_dates[-1] if all_dates else ""
week_options_js = json.dumps(week_options)
data_start_js   = json.dumps(data_start)
data_end_js     = json.dumps(data_end)

# ── JS blobs ───────────────────────────────────────────────────────────────────
detail_rows_js  = json.dumps(detail_rows)
account_rows_js = json.dumps(account_rows)
sdk_type_pie_js = json.dumps(SDK_TYPE_PIE)
sdk_tv_js       = json.dumps(SDK_TV_LIST)
timeseries_js   = json.dumps(timeseries)
daily_rows_js   = json.dumps(daily_rows)
date_keys_js    = json.dumps(all_dates)
date_labels_js  = json.dumps(date_labels)
ticket_labels_js= json.dumps(["Mobile Flow Analyzer Dashboard", "Mobile SDK Dashboard", "Mobile Flow Analyzer"])
ticket_values_js= json.dumps([1, 1, 1])
pendo_scan_js   = json.dumps(pendo_cat["Scan"]["features"])
pendo_conn_js   = json.dumps(pendo_cat["Connection"]["features"])
pendo_report_js = json.dumps(pendo_cat["Report"]["features"])
internals_js    = json.dumps(list(INTERNALS))
sdk_product_js  = json.dumps(list(SDK_PRODUCT_TYPES))

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
    .status-bar {{ background:#3B0764; padding:5px 24px; display:flex; justify-content:flex-end; gap:20px; font-size:10px; color:rgba(255,255,255,.55); }}
    .dot {{ display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
    .dot-live {{ background:#10B981; animation:pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
    .main {{ padding:18px 24px; max-width:1680px; margin:0 auto; }}
    .note-bar {{ background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; padding:8px 14px; margin-bottom:16px; font-size:11px; color:#1E40AF; }}
    .filters-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 18px; margin-bottom:18px; box-shadow:0 1px 4px rgba(0,0,0,.05); }}
    .filters-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
    .filters-label {{ font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; }}
    .btn-reset {{ font-size:11px; color:var(--primary); background:none; border:none; cursor:pointer; font-family:inherit; }}
    .filters-grid {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; }}
    .fg label {{ display:block; font-size:10px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }}
    .fg select {{ width:100%; padding:6px 24px 6px 9px; border:1px solid var(--border); border-radius:6px; font-size:12px; color:var(--text); background:#FAFAFA; font-family:inherit; outline:none; appearance:none;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2394A3B8'/%3E%3C/svg%3E"); background-repeat:no-repeat; background-position:right 8px center; }}
    .fg select:focus {{ border-color:var(--primary); box-shadow:0 0 0 3px rgba(109,40,217,.1); }}
    .kpi-row {{ display:grid; grid-template-columns:repeat(8,1fr); gap:12px; margin-bottom:18px; }}
    .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; box-shadow:0 1px 4px rgba(0,0,0,.05); position:relative; overflow:hidden; }}
    .kpi::after {{ content:''; position:absolute; top:0;left:0;right:0;height:3px; }}
    .kpi.c-purple::after {{ background:var(--primary); }} .kpi.c-blue::after {{ background:var(--blue); }}
    .kpi.c-teal::after   {{ background:var(--teal); }}   .kpi.c-indigo::after {{ background:var(--indigo); }}
    .kpi.c-amber::after  {{ background:var(--amber); }}  .kpi.c-red::after    {{ background:var(--red); }}
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
    tbody tr:hover {{ background:#FAFBFF; }} tbody tr:last-child {{ border-bottom:none; }}
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
    .b-none {{ color:#CBD5E1; font-size:12px; }}
    .table-footer {{ display:flex; align-items:center; justify-content:space-between; padding:10px 18px; border-top:1px solid var(--border); }}
    .page-info {{ font-size:11px; color:var(--muted); }}
    .pag {{ display:flex; align-items:center; gap:6px; }}
    .pag-btn {{ padding:5px 10px; border:1px solid var(--border); border-radius:5px; font-size:12px; cursor:pointer; background:white; font-family:inherit; }}
    .pag-btn:hover {{ background:#F8FAFC; }}
    .pag-btn:disabled {{ opacity:.4; cursor:default; }}
    .pag-pages {{ font-size:11px; color:var(--muted); min-width:80px; text-align:center; }}
    @media(max-width:1400px) {{ .kpi-row{{grid-template-columns:repeat(4,1fr)}} .charts-grid{{grid-template-columns:repeat(2,1fr)}} }}
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
    <div class="pill green">● Live — Coralogix + HubSpot</div>
  </div>
</header>
<div class="status-bar">
  <span><span class="dot dot-live"></span>Coralogix: last 14 days · prod only</span>
  <span><span class="dot dot-live"></span>HubSpot: Owner / SE / TAM · MFA/Mobile tickets</span>
  <span style="color:rgba(255,255,255,.4)">Users: email (MFA) · service account (SDK)</span>
</div>

<div class="main">
  <div class="note-bar">
    <strong>Live — Coralogix + HubSpot.</strong> Last 14 days · production only.
    <strong>{len(all_tenants)} active tenants</strong> ({len(ext_tenants)} external) ·
    <strong>{unique_users} active users</strong> ·
    <strong>{total_scans:,} total scans</strong>.
    New Tenant = HubSpot MFA/Mobile deal closed this month ·
    Renewal = MFA/Mobile/All Products deal ending Apr–May 2026 ·
    Support Tickets = tickets with "MFA" or "Mobile" in subject.
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
          <option value="all">All data</option>
          <option value="7">Last 7 days</option>
          <option value="3">Last 3 days</option>
          <!-- week options injected by JS -->
          <option value="custom">Custom range…</option>
        </select>
        <div id="custom-date-wrap" style="display:none;margin-top:5px;align-items:center;gap:4px">
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
    </div>
  </div>

  <!-- KPIs -->
  <div class="kpi-row">
    <div class="kpi c-blue">  <div class="kpi-label">Active Tenants</div><div class="kpi-val" id="k-tenants">{len(ext_tenants)}</div><div class="kpi-sub" id="k-tenants-sub">Last 14d · excl. internals</div></div>
    <div class="kpi c-teal">  <div class="kpi-label">Active Users</div><div class="kpi-val" id="k-users">{unique_users}</div><div class="kpi-sub">email (MFA) + service acct (SDK)</div></div>
    <div class="kpi c-indigo"><div class="kpi-label">Total Scans</div><div class="kpi-val" id="k-scans">{total_scans:,}</div><div class="kpi-sub" id="k-scans-sub">Last 14 days</div></div>
    <div class="kpi c-amber"> <div class="kpi-label">Avg Issues / Scan</div><div class="kpi-val" id="k-issues">—</div><div class="kpi-sub">total issues ÷ scans</div></div>
    <div class="kpi c-red">   <div class="kpi-label">Avg Critical / Scan</div><div class="kpi-val" id="k-crit">—</div><div class="kpi-sub">critical issues ÷ scans</div></div>
    <div class="kpi c-green"> <div class="kpi-label">New Tenants</div><div class="kpi-val">{new_count}</div><div class="kpi-sub">MFA/Mobile deal · closed this month</div></div>
    <div class="kpi c-violet"><div class="kpi-label">Upcoming Renewals</div><div class="kpi-val">{renewal_count}</div><div class="kpi-sub">deal ending Apr–May 2026</div></div>
    <div class="kpi c-purple"><div class="kpi-label">Support Tickets</div><div class="kpi-val">{CURRENT_MONTH_TICKETS}</div><div class="kpi-sub">MFA/Mobile subject · Apr 2026</div></div>
  </div>

  <!-- CHARTS -->
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Active Tenants Over Time</div><span class="chart-source">Coralogix · 14d · overall</span></div></div>
      <div class="chart-wrap"><canvas id="ch-tenants"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Support Tickets by Type — Apr 2026</div><span class="chart-source">HubSpot · MFA/Mobile subject</span></div></div>
      <div class="chart-wrap"><canvas id="ch-tickets"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Total Scans Over Time</div><span class="chart-source">Coralogix · 14d · overall</span></div></div>
      <div class="chart-wrap"><canvas id="ch-scans"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">Active Users Over Time</div><span class="chart-source">Coralogix · 14d · overall</span></div></div>
      <div class="chart-wrap"><canvas id="ch-users"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">SDK Type Breakdown</div><span class="chart-source">Coralogix · by scan count</span></div></div>
      <div class="chart-wrap"><canvas id="ch-sdk-type"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div><div class="chart-title">SDK Type + Variant Breakdown</div><span class="chart-source">Coralogix · by scan count</span></div></div>
      <div class="chart-wrap"><canvas id="ch-sdk-tv"></canvas></div>
    </div>
  </div>

  <!-- MFA FEATURE ACTIVITY ─────────────────────────────────────────────── -->
  <div id="mfa-section">
  <div class="section-label" style="margin-top:8px">📊 MFA Feature Activity <span>Pendo · {pendo_date_range} · MFA only</span></div>

  <!-- MFA KPI row -->
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px">
    <div class="kpi c-purple">
      <div class="kpi-label">Users — Scan Features</div>
      <div class="kpi-val">{pendo_cat["Scan"]["users"]}</div>
      <div class="kpi-sub">Pendo · {pendo_date_range} · unique visitors</div>
    </div>
    <div class="kpi c-blue">
      <div class="kpi-label">Users — Connection Features</div>
      <div class="kpi-val">{pendo_cat["Connection"]["users"]}</div>
      <div class="kpi-sub">Pendo · {pendo_date_range} · unique visitors</div>
    </div>
    <div class="kpi c-teal">
      <div class="kpi-label">Users — Report Features</div>
      <div class="kpi-val">{pendo_cat["Report"]["users"]}</div>
      <div class="kpi-sub">Pendo · {pendo_date_range} · unique visitors</div>
    </div>
  </div>

  <!-- MFA time series -->
  <div class="charts-grid" style="grid-template-columns:1fr;margin-bottom:18px">
    <div class="chart-card">
      <div class="chart-header">
        <div>
          <div class="chart-title">MFA Active Users Over Time</div>
          <span class="chart-source">Coralogix daily MFA users · {coralogix_date_range}</span>
        </div>
      </div>
      <div class="chart-wrap" style="height:200px"><canvas id="ch-mfa-trend"></canvas></div>
    </div>
  </div>

  <!-- Feature bar charts: one per category -->
  <div class="charts-grid" style="margin-bottom:18px">
    <div class="chart-card">
      <div class="chart-header"><div>
        <div class="chart-title">Scan Features — Events ({pendo_date_range})</div>
        <span class="chart-source">Pendo · click count per feature</span>
      </div></div>
      <div class="chart-wrap" style="height:{max(160, len(pendo_cat['Scan']['features'])*30)}px"><canvas id="ch-pendo-scan"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div>
        <div class="chart-title">Connection Features — Events ({pendo_date_range})</div>
        <span class="chart-source">Pendo · click count per feature</span>
      </div></div>
      <div class="chart-wrap" style="height:{max(160, len(pendo_cat['Connection']['features'])*30)}px"><canvas id="ch-pendo-conn"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-header"><div>
        <div class="chart-title">Report Features — Events ({pendo_date_range})</div>
        <span class="chart-source">Pendo · click count per feature</span>
      </div></div>
      <div class="chart-wrap" style="height:{max(160, len(pendo_cat['Report']['features'])*30)}px"><canvas id="ch-pendo-report"></canvas></div>
    </div>
  </div>
  </div><!-- /#mfa-section -->

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
  <div class="section-label">👤 Users <span>Per-user scan detail</span></div>
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
          <th onclick="sortDet('scans')">Scans ↕</th>
          <th onclick="sortDet('total_issues')">Total Issues ↕</th>
          <th onclick="sortDet('critical_issues')">Critical Issues ↕</th>
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
const TIMESERIES    = {timeseries_js};
const DAILY_ROWS    = {daily_rows_js};
const DATE_KEYS     = {date_keys_js};
const DATE_LABELS   = {date_labels_js};
const SDK_TYPE_PIE  = {sdk_type_pie_js};
const SDK_TV_LIST   = {sdk_tv_js};
const DETAIL_ROWS   = {detail_rows_js};
const ACCOUNT_ROWS  = {account_rows_js};
const TICKET_LABELS  = {ticket_labels_js};
const TICKET_VALUES  = {ticket_values_js};
const PENDO_SCAN     = {pendo_scan_js};
const PENDO_CONN     = {pendo_conn_js};
const PENDO_REPORT   = {pendo_report_js};
const INTERNALS      = new Set({internals_js});
const SDK_PRODUCTS  = new Set({sdk_product_js}); // Espresso, WebdriverIO, XCUITest, Appium, MCP Server

// Static HubSpot metadata per tenant (latest_scan, tickets, renewal, is_new) — not date-dependent
const ACCT_META = {{}};
ACCOUNT_ROWS.forEach(r => {{ ACCT_META[r.tenantName] = r; }});

// Date filter helpers
const WEEK_OPTIONS = {week_options_js};
const DATA_START   = {data_start_js};
const DATA_END     = {data_end_js};

const PER_PAGE = 10;

// ── Populate SE filter ────────────────────────────────────────────────────────
(function() {{
  const ses = [...new Set(ACCOUNT_ROWS.map(r => r.se).filter(s => s && s !== '\u2014'))].sort();
  const sel = document.getElementById('f-se');
  ses.forEach(s => {{ const o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o); }});
}})();

// ── Populate date filter with week options ────────────────────────────────────
(function() {{
  const sel = document.getElementById('f-date');
  // Insert week options before the "Custom…" option (last child)
  const customOpt = sel.lastElementChild;
  const sep = document.createElement('option');
  sep.disabled = true; sep.textContent = '\u2500\u2500 By calendar week \u2500\u2500';
  sel.insertBefore(sep, customOpt);
  WEEK_OPTIONS.forEach((w, i) => {{
    const o = document.createElement('option');
    o.value = 'week_' + i; o.textContent = w.label;
    sel.insertBefore(o, customOpt);
  }});
  // Set custom date picker bounds + default values
  const from = document.getElementById('f-date-from');
  const to   = document.getElementById('f-date-to');
  from.min = to.min = DATA_START;
  from.max = to.max = DATA_END;
  from.value = DATA_START;
  to.value   = DATA_END;
}})();

function onDateChange() {{
  const val  = document.getElementById('f-date').value;
  const wrap = document.getElementById('custom-date-wrap');
  wrap.style.display = val === 'custom' ? 'flex' : 'none';
  applyFilters();
}}

function getDateRange() {{
  const val = document.getElementById('f-date').value;
  const last = DATE_KEYS[DATE_KEYS.length - 1] || '';
  if (val === 'all')    return [DATE_KEYS[0] || '', last];
  if (val === 'custom') return [
    document.getElementById('f-date-from').value || DATE_KEYS[0] || '',
    document.getElementById('f-date-to').value   || last
  ];
  if (val.startsWith('week_')) {{
    const w = WEEK_OPTIONS[parseInt(val.slice(5))];
    return [w.start, w.end];
  }}
  // Rolling: last N days
  const days  = parseInt(val) || 14;
  const start = DATE_KEYS.length > days ? DATE_KEYS[DATE_KEYS.length - days] : (DATE_KEYS[0] || '');
  return [start, last];
}}

// ── Charts ────────────────────────────────────────────────────────────────────
const CC = ['#6D28D9','#3B82F6','#0D9488','#F59E0B','#EF4444','#10B981','#8B5CF6','#06B6D4'];
const CHARTS = {{}};

function mkLine(id, label, color, labels, data) {{
  return new Chart(document.getElementById(id), {{
    type:'line',
    data:{{ labels, datasets:[{{ label, data, borderColor:color, backgroundColor:color+'22', borderWidth:2, pointRadius:3, tension:0.3, fill:true }}] }},
    options:{{ responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{ backgroundColor:'#1E293B', bodyFont:{{size:11}}, padding:8, cornerRadius:6 }} }},
      scales:{{ x:{{ grid:{{display:false}}, ticks:{{font:{{size:9}},color:'#94A3B8'}} }}, y:{{ grid:{{color:'#F1F5F9'}}, ticks:{{font:{{size:10}},color:'#94A3B8'}}, beginAtZero:true }} }} }}
  }});
}}

// Compute daily series. startDate/endDate narrow the x-axis; default = full range.
function computeDaily(filteredDailyRows, startDate, endDate) {{
  startDate = startDate || DATE_KEYS[0] || '';
  endDate   = endDate   || DATE_KEYS[DATE_KEYS.length - 1] || '';
  const keys   = DATE_KEYS.filter(d => d >= startDate && d <= endDate);
  const labels = keys.map(d => DATE_LABELS[DATE_KEYS.indexOf(d)]);
  const tMap = {{}}, uMap = {{}}, sMap = {{}};
  filteredDailyRows.forEach(r => {{
    if (!tMap[r.date]) tMap[r.date] = new Set();
    if (!uMap[r.date]) uMap[r.date] = new Set();
    if (r.tenantName) tMap[r.date].add(r.tenantName);
    if (r.userId)     uMap[r.date].add(r.userId);
    sMap[r.date] = (sMap[r.date] || 0) + (r.scans || 0);
  }});
  return {{
    labels,
    tenants: keys.map(d => tMap[d] ? tMap[d].size : 0),
    users:   keys.map(d => uMap[d] ? uMap[d].size : 0),
    scans:   keys.map(d => sMap[d] || 0),
  }};
}}

function initCharts() {{
  const baseline = computeDaily(DAILY_ROWS.filter(r => !r.isInternal));
  CHARTS.tenants = mkLine('ch-tenants','Active Tenants','#3B82F6', DATE_LABELS, baseline.tenants);
  CHARTS.scans   = mkLine('ch-scans',  'Total Scans',  '#6D28D9', DATE_LABELS,  baseline.scans);
  CHARTS.users   = mkLine('ch-users',  'Active Users',  '#0D9488', DATE_LABELS, baseline.users);

  // Tickets pie — one distinct color per ticket
  const TICKET_COLORS = ['#6D28D9','#0D9488','#F59E0B','#EF4444','#3B82F6','#10B981'];
  CHARTS.tickets = new Chart(document.getElementById('ch-tickets'), {{
    type:'pie',
    data:{{ labels:TICKET_LABELS, datasets:[{{ data:TICKET_VALUES,
      backgroundColor:TICKET_LABELS.map((_,i)=>TICKET_COLORS[i%TICKET_COLORS.length]+'CC'),
      borderColor:TICKET_LABELS.map((_,i)=>TICKET_COLORS[i%TICKET_COLORS.length]), borderWidth:2 }}] }},
    options:{{ responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{position:'bottom',labels:{{font:{{size:10}},padding:10,boxWidth:12}}}},
        tooltip:{{backgroundColor:'#1E293B',callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed+' ticket'+(ctx.parsed!==1?'s':'')}}}} }} }}
  }});

  // SDK type pie
  CHARTS.sdkType = new Chart(document.getElementById('ch-sdk-type'), {{
    type:'pie',
    data:{{ labels:SDK_TYPE_PIE.map(s=>s.sdkType),
            datasets:[{{ data:SDK_TYPE_PIE.map(s=>s.scans),
              backgroundColor:SDK_TYPE_PIE.map((_,i)=>CC[i%CC.length]+'CC'),
              borderColor:SDK_TYPE_PIE.map((_,i)=>CC[i%CC.length]), borderWidth:2 }}] }},
    options:{{ responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{position:'bottom',labels:{{font:{{size:9}},padding:8,boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed.toLocaleString()+' scans'}}}} }} }}
  }});

  // ── MFA feature activity (Pendo) ─────────────────────────────────────────

  // MFA users over time — Coralogix daily data filtered to MFA
  const mfaDaily = computeDaily(DAILY_ROWS.filter(r => !r.isInternal && r.sdkType === 'MFA'));
  CHARTS.mfaTrend = mkLine('ch-mfa-trend', 'MFA Active Users', '#6D28D9', DATE_LABELS, mfaDaily.users);

  // Helper: horizontal bar chart for Pendo feature data
  function mkPendoBar(id, data, color) {{
    return new Chart(document.getElementById(id), {{
      type: 'bar',
      data: {{
        labels: data.map(d => d.feature),
        datasets: [{{ data: data.map(d => d.events),
          backgroundColor: color + '99', borderColor: color, borderWidth: 1 }}]
      }},
      options: {{
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{display:false}},
          tooltip: {{ backgroundColor:'#1E293B',
            callbacks: {{ label: ctx => ' ' + ctx.parsed.x.toLocaleString() + ' events' }} }} }},
        scales: {{
          x: {{ grid:{{color:'#F1F5F9'}}, ticks:{{font:{{size:9}},color:'#94A3B8'}}, beginAtZero:true }},
          y: {{ grid:{{display:false}}, ticks:{{font:{{size:10}},color:'#64748B'}} }}
        }}
      }}
    }});
  }}

  CHARTS.pendoScan   = mkPendoBar('ch-pendo-scan',   PENDO_SCAN,   '#6D28D9');
  CHARTS.pendoConn   = mkPendoBar('ch-pendo-conn',   PENDO_CONN,   '#3B82F6');
  CHARTS.pendoReport = mkPendoBar('ch-pendo-report', PENDO_REPORT, '#0D9488');

  // SDK type+variant horizontal bar
  CHARTS.sdkTV = new Chart(document.getElementById('ch-sdk-tv'), {{
    type:'bar',
    data:{{ labels:SDK_TV_LIST.map(s=>s.label),
            datasets:[{{ data:SDK_TV_LIST.map(s=>s.scans),
              backgroundColor:SDK_TV_LIST.map((_,i)=>CC[i%CC.length]+'BB'),
              borderColor:SDK_TV_LIST.map((_,i)=>CC[i%CC.length]), borderWidth:1 }}] }},
    options:{{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{backgroundColor:'#1E293B',callbacks:{{label:ctx=>' '+ctx.parsed.x.toLocaleString()+' scans'}}}} }},
      scales:{{ x:{{grid:{{color:'#F1F5F9'}},ticks:{{font:{{size:9}},color:'#94A3B8'}},beginAtZero:true}}, y:{{grid:{{display:false}},ticks:{{font:{{size:9}},color:'#64748B'}}}} }} }}
  }});
}}

// ── State ─────────────────────────────────────────────────────────────────────
let detPage = 0, acctPage = 0;
let detSort  = {{key:'scans', dir:-1}};
let acctSort = {{key:'total_scans', dir:-1}};
let filteredDaily    = [...DAILY_ROWS];
let filteredDetail   = [...DETAIL_ROWS];
let filteredAccounts = [...ACCOUNT_ROWS];

// ── Chart update — receives pre-filtered daily rows from applyFilters ─────────
function updateCharts(filteredDaily) {{
  const [startDate, endDate] = getDateRange();

  // SDK type pie
  const sdkTypeAgg = {{}};
  filteredDaily.forEach(r => {{ sdkTypeAgg[r.sdkType] = (sdkTypeAgg[r.sdkType]||0) + r.scans; }});
  const sortedTypes = Object.entries(sdkTypeAgg).sort((a,b) => b[1]-a[1]);
  CHARTS.sdkType.data.labels = sortedTypes.map(([k]) => k);
  CHARTS.sdkType.data.datasets[0].data = sortedTypes.map(([,v]) => v);
  CHARTS.sdkType.data.datasets[0].backgroundColor = sortedTypes.map((_,i) => CC[i%CC.length]+'CC');
  CHARTS.sdkType.data.datasets[0].borderColor = sortedTypes.map((_,i) => CC[i%CC.length]);
  CHARTS.sdkType.update();

  // SDK type+variant bar
  const sdkTVAgg = {{}};
  filteredDaily.forEach(r => {{
    const variant = r.sdkVariant || '\u2014';
    const key = r.sdkType + ' / ' + variant;
    sdkTVAgg[key] = (sdkTVAgg[key]||0) + r.scans;
  }});
  const sortedTV = Object.entries(sdkTVAgg).sort((a,b) => b[1]-a[1]);
  CHARTS.sdkTV.data.labels = sortedTV.map(([k]) => k);
  CHARTS.sdkTV.data.datasets[0].data = sortedTV.map(([,v]) => v);
  CHARTS.sdkTV.data.datasets[0].backgroundColor = sortedTV.map((_,i) => CC[i%CC.length]+'BB');
  CHARTS.sdkTV.data.datasets[0].borderColor = sortedTV.map((_,i) => CC[i%CC.length]);
  CHARTS.sdkTV.update();

  // Line charts — daily tenants / users / scans (x-axis labels match date range)
  const daily = computeDaily(filteredDaily, startDate, endDate);
  CHARTS.tenants.data.labels = daily.labels;
  CHARTS.tenants.data.datasets[0].data = daily.tenants;
  CHARTS.users.data.labels = daily.labels;
  CHARTS.users.data.datasets[0].data = daily.users;
  CHARTS.scans.data.labels = daily.labels;
  CHARTS.scans.data.datasets[0].data = daily.scans;
  CHARTS.tenants.update();
  CHARTS.users.update();
  CHARTS.scans.update();

  // MFA trend line (Coralogix MFA-only users, responds to date range)
  if (CHARTS.mfaTrend) {{
    const mfaRows  = filteredDaily.filter(r => !r.isInternal && r.sdkType === 'MFA');
    const mfaDaily = computeDaily(mfaRows, startDate, endDate);
    CHARTS.mfaTrend.data.labels = mfaDaily.labels;
    CHARTS.mfaTrend.data.datasets[0].data = mfaDaily.users;
    CHARTS.mfaTrend.update();
  }}
}}

// ── Filters ───────────────────────────────────────────────────────────────────
function applyFilters() {{
  const product      = document.getElementById('f-product').value;
  const tenant       = document.getElementById('f-tenant').value;
  const sdk          = document.getElementById('f-sdk').value;
  const showInternal = document.getElementById('f-internals').value === 'true';
  const se           = document.getElementById('f-se').value;
  const [startDate, endDate] = getDateRange();

  // Single filtered view of DAILY_ROWS — source of truth for everything below
  filteredDaily = DAILY_ROWS.filter(r => {{
    if (r.date < startDate || r.date > endDate) return false;
    if (!showInternal && r.isInternal) return false;
    if (tenant  !== 'all' && r.tenantName !== tenant) return false;
    if (sdk     !== 'all' && r.sdkType   !== sdk)    return false;
    if (product === 'mfa' && r.sdkType   !== 'MFA')  return false;
    if (product === 'sdk' && r.sdkType   === 'MFA')  return false;
    if (se !== 'all' && r.se !== se) return false;
    return true;
  }});

  // Re-aggregate detail rows (per tenant + userId) from filteredDaily
  const detMap = {{}};
  filteredDaily.forEach(function(r) {{
    const key = r.tenantName + '|' + (r.userId || '');
    if (!detMap[key]) {{
      detMap[key] = {{
        tenantName: r.tenantName, userId: r.userId,
        sdkTypes: [], sdkType: r.sdkType,
        scans: 0, total_issues: 0, critical_issues: 0,
        se: r.se, owner: r.owner, tam: r.tam, is_internal: r.isInternal
      }};
    }}
    if (detMap[key].sdkTypes.indexOf(r.sdkType) < 0) detMap[key].sdkTypes.push(r.sdkType);
    detMap[key].scans           += r.scans;
    detMap[key].total_issues    += (r.total_issues || 0);
    detMap[key].critical_issues += (r.critical_issues || 0);
  }});
  filteredDetail = Object.values(detMap);
  filteredDetail.forEach(function(d) {{
    d.sdkTypes.sort();
    d.sdkType = d.sdkTypes.join(', ');
  }});

  // Re-aggregate account rows (per tenant) from filteredDaily
  const acctMap = {{}};
  filteredDaily.forEach(function(r) {{
    if (!acctMap[r.tenantName]) {{
      const m = ACCT_META[r.tenantName] || {{}};
      acctMap[r.tenantName] = {{
        tenantName:    r.tenantName,
        total_scans:   0,
        latest_scan:   m.latest_scan   || '\u2014',
        owner:         r.owner         || '\u2014',
        se:            r.se            || '\u2014',
        tam:           r.tam           || '\u2014',
        tickets_month: m.tickets_month || 0,
        is_internal:   r.isInternal,
        is_new:        m.is_new        || false,
        renewal:       m.renewal       || null
      }};
    }}
    acctMap[r.tenantName].total_scans += r.scans;
  }});
  filteredAccounts = Object.values(acctMap);

  // Show/hide MFA Feature Activity section based on product filter
  const mfaSection = document.getElementById('mfa-section');
  if (mfaSection) mfaSection.style.display = product === 'sdk' ? 'none' : '';

  detPage = 0; acctPage = 0;
  updateKPIs();
  updateCharts(filteredDaily);
  renderAccounts();
  renderDetail();
}}

function resetFilters() {{
  ['f-product','f-tenant','f-sdk','f-date','f-internals','f-se'].forEach(id => {{
    const el = document.getElementById(id); if (el) el.selectedIndex = 0;
  }});
  document.getElementById('custom-date-wrap').style.display = 'none';
  document.getElementById('f-date-from').value = DATA_START;
  document.getElementById('f-date-to').value   = DATA_END;
  applyFilters();
}}

// ── KPIs — computed directly from filteredDaily (same source as charts) ───────
function updateKPIs() {{
  const rows    = filteredDaily;
  const tenantSet = {{}}, userSet = {{}};
  let scans = 0, issues = 0, crit = 0;
  rows.forEach(function(r) {{
    tenantSet[r.tenantName] = 1;
    if (r.userId) userSet[r.userId] = 1;
    scans  += r.scans;
    issues += (r.total_issues    || 0);
    crit   += (r.critical_issues || 0);
  }});
  const tenants = Object.keys(tenantSet).length;
  const users   = Object.keys(userSet).length;

  document.getElementById('k-tenants').textContent = tenants;
  document.getElementById('k-users').textContent   = users;
  document.getElementById('k-scans').textContent   = scans.toLocaleString();
  document.getElementById('k-issues').textContent  = scans ? (issues/scans).toFixed(1) : '0';
  document.getElementById('k-crit').textContent    = scans ? (crit/scans).toFixed(1)   : '0';

  // Update KPI subtitles to reflect active date range
  const [s, e] = getDateRange();
  const rangeLabel = (s === DATE_KEYS[0] && e === DATE_KEYS[DATE_KEYS.length-1])
    ? 'Last 14d · excl. internals'
    : s + ' \u2013 ' + e + ' · excl. internals';
  const sub1 = document.getElementById('k-tenants-sub');
  const sub2 = document.getElementById('k-scans-sub');
  if (sub1) sub1.textContent = rangeLabel;
  if (sub2) sub2.textContent = rangeLabel;
}}

// ── Render helpers ────────────────────────────────────────────────────────────
function dash(v) {{
  return (v && v !== '\u2014') ? v : '<span class="b-none">\u2014</span>';
}}
function sdkBadge(t) {{
  return '<span class="badge ' + (t==='MFA'?'b-mfa':'b-sdk') + '">' + t + '</span>';
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

  document.getElementById('acct-body').innerHTML = page.map(r => `
    <tr>
      <td><strong>${{r.tenantName}}</strong></td>
      <td class="num">${{r.total_scans.toLocaleString()}}</td>
      <td style="color:var(--muted);font-size:11px">${{r.latest_scan||'\u2014'}}</td>
      <td>${{dash(r.owner)}}</td>
      <td>${{dash(r.se)}}</td>
      <td>${{dash(r.tam)}}</td>
      <td>
        ${{r.is_new     ? '<span class="badge b-new">New</span> '     : ''}}
        ${{r.renewal    ? '<span class="badge b-renewal">Renewal</span> ' : ''}}
        ${{r.is_internal? '<span class="badge b-int">Internal</span>' : ''}}
      </td>
    </tr>`).join('');

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
      <td class="mono">${{r.userId || '<span class="b-none">\u2014</span>'}}</td>
      <td class="num">${{r.scans.toLocaleString()}}</td>
      <td class="num-muted">${{r.total_issues.toLocaleString()}}</td>
      <td class="num-muted" style="color:${{r.critical_issues>0?'var(--red)':'inherit'}}">${{r.critical_issues.toLocaleString()}}</td>
    </tr>`).join('');

  document.getElementById('det-info').textContent = total + ' row' + (total!==1?'s':'');
  document.getElementById('det-pages').textContent = 'Page ' + (detPage+1) + ' / ' + pages;
  document.getElementById('det-prev').disabled = detPage === 0;
  document.getElementById('det-next').disabled = detPage >= pages-1;
}}

// ── Export ────────────────────────────────────────────────────────────────────
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
  const h = ['Tenant','User','Scans','Total Issues','Critical Issues'];
  const d = filteredDetail.map(r=>[r.tenantName,r.userId,r.scans,r.total_issues,r.critical_issues]);
  const a = document.createElement('a'); a.href='data:text/csv,'+encodeURIComponent(toCSV(h,d));
  a.download='users_'+new Date().toISOString().slice(0,10)+'.csv'; a.click();
}}

// ── Boot ──────────────────────────────────────────────────────────────────────
initCharts();
applyFilters();
</script>
</body>
</html>"""

out_path = os.path.join(OUTPUTS, "mobile-products-dashboard.html")
with open(out_path, "w") as f:
    f.write(html)
print(f"Written: {out_path}  ({len(html):,} chars)")
print(f"SDK types (normalized): {[s['sdkType'] for s in SDK_TYPE_PIE]}")
print(f"SDK type+variant combos: {len(SDK_TV_LIST)}")
print(f"Detail rows: {len(detail_rows)}, Account rows: {len(account_rows)}")
