#!/usr/bin/env python3
"""
Fetch account metadata from HubSpot: owner (AE), SE, TAM, renewal date.
Matches HubSpot companies to Coralogix tenant names and writes hubspot_accounts.json.

Requires: HUBSPOT_TOKEN environment variable (HubSpot Private App token)
Scopes needed: crm.objects.companies.read, crm.objects.deals.read
"""
import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))

TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
if not TOKEN:
    raise EnvironmentError("HUBSPOT_TOKEN is not set. See .env.example for setup instructions.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# ── Owner ID → Name map (fetched once from HubSpot /owners endpoint) ──────────
def fetch_owners():
    url = "https://api.hubapi.com/crm/v3/owners?limit=200"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    owners = {}
    for o in data.get("results", []):
        name = f"{o.get('firstName','')} {o.get('lastName','')}".strip()
        owners[str(o["id"])] = name
    return owners

# ── Search HubSpot companies by name ──────────────────────────────────────────
def search_company(name, owners):
    payload = json.dumps({
        "filterGroups": [],
        "query": name,
        "properties": ["name", "hubspot_owner_id", "se_owner", "tam_owner", "createdate"],
        "limit": 5,
    }).encode()
    req = urllib.request.Request(
        "https://api.hubapi.com/crm/v3/objects/companies/search",
        data=payload, headers=HEADERS, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  ⚠ search error for '{name}': {e}")
        return None

    results = data.get("results", [])
    if not results:
        return None

    # Pick the best match: exact or starts-with
    name_lower = name.lower()
    best = None
    for r in results:
        cname = (r["properties"].get("name") or "").lower()
        if cname == name_lower:
            best = r
            break
        if cname.startswith(name_lower) or name_lower in cname:
            if not best:
                best = r

    if not best:
        best = results[0]  # fallback: first result

    props = best["properties"]
    return {
        "hs_id":   best["id"],
        "name":    props.get("name"),
        "owner":   owners.get(str(props.get("hubspot_owner_id") or ""), "—"),
        "se":      owners.get(str(props.get("se_owner") or ""), "—"),
        "tam":     owners.get(str(props.get("tam_owner") or ""), "—"),
        "is_new":  is_new_account(props.get("createdate")),
    }

def is_new_account(createdate_str):
    """True if account was created within the last 90 days."""
    if not createdate_str:
        return False
    try:
        created = datetime.fromisoformat(createdate_str.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
        return age_days <= 90
    except Exception:
        return False

# ── Fetch renewal date from deals associated with a company ───────────────────
def fetch_renewal_date(hs_id):
    """Returns the next upcoming renewal deal closedate (YYYY-MM-DD) or None."""
    url = f"https://api.hubapi.com/crm/v4/objects/companies/{hs_id}/associations/deals"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception:
        return None

    deal_ids = [str(r["toObjectId"]) for r in data.get("results", [])]
    if not deal_ids:
        return None

    # Batch-fetch deal details
    ids_param = "&".join(f"id={d}" for d in deal_ids[:20])
    url2 = f"https://api.hubapi.com/crm/v3/objects/deals/batch/read"
    payload = json.dumps({
        "inputs": [{"id": d} for d in deal_ids[:20]],
        "properties": ["dealname", "closedate", "dealstage"],
    }).encode()
    req2 = urllib.request.Request(url2, data=payload, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req2, timeout=20) as r:
            data2 = json.loads(r.read())
    except Exception:
        return None

    now = datetime.now(timezone.utc)
    renewal_dates = []
    for deal in data2.get("results", []):
        name = (deal["properties"].get("dealname") or "").lower()
        closedate_str = deal["properties"].get("closedate")
        if "renewal" in name and closedate_str:
            try:
                cd = datetime.fromisoformat(closedate_str.replace("Z", "+00:00"))
                if cd >= now:  # only future renewals
                    renewal_dates.append(cd.strftime("%Y-%m-%d"))
            except Exception:
                pass

    return sorted(renewal_dates)[0] if renewal_dates else None

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    # Load tenant names from Coralogix data
    rows_path = os.path.join(BASE, "rows_with_sa.json")
    if not os.path.exists(rows_path):
        raise FileNotFoundError(f"{rows_path} not found — run fetch_with_sa.py first")

    rows = json.load(open(rows_path))
    tenant_names = sorted(set(r["tenantName"] for r in rows if r.get("tenantName")))
    print(f"Found {len(tenant_names)} unique tenants to look up in HubSpot")

    print("Fetching HubSpot owners list…")
    owners = fetch_owners()
    print(f"  Loaded {len(owners)} owners")

    results = {}
    for i, name in enumerate(tenant_names, 1):
        print(f"  [{i}/{len(tenant_names)}] {name}…", end=" ", flush=True)
        company = search_company(name, owners)
        if not company:
            print("not found")
            results[name] = {"owner": "—", "se": "—", "tam": "—",
                             "renewal": None, "is_new": False}
            continue

        renewal = fetch_renewal_date(company["hs_id"])
        results[name] = {
            "owner":   company["owner"],
            "se":      company["se"],
            "tam":     company["tam"],
            "renewal": renewal,
            "is_new":  company["is_new"],
        }
        print(f"✓  owner={company['owner']}, SE={company['se']}, renewal={renewal}")

    out = os.path.join(BASE, "hubspot_accounts.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} accounts → {out}")

if __name__ == "__main__":
    main()
