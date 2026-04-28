#!/usr/bin/env python3
"""
Fetch mobile scan data from BigQuery → rows_with_sa.json

Replaces the Coralogix fetch. Uses the analytics.scan_success table,
filtered to MOBILE_SDK and MOBILE_FLOW_ANALYZER products, last 14 days.

Authentication: uses Application Default Credentials.
Run once: gcloud auth application-default login
Or set: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
"""
import json, os
from google.cloud import bigquery

BASE    = os.path.dirname(os.path.abspath(__file__))
PROJECT = "production-267908"

client = bigquery.Client(project=PROJECT)

QUERY = """
SELECT
  t.name                       AS tenantName,
  s.owner_id                   AS serviceAccountId,
  usr.email                    AS email,
  s.os_name                    AS platformName,
  sd.type                      AS sdkType,
  p.name                       AS productName,
  DATE(s._PARTITIONTIME)       AS date,
  COUNT(*)                     AS scans
FROM `production-267908.analytics.scan_success` s
LEFT JOIN `production-267908.analytics.d_sdk_types` sd  ON s.sdk_type    = sd.id
LEFT JOIN `production-267908.analytics.d_products`  p   ON p.id          = s.product_name
LEFT JOIN `production-267908.analytics.tenants`     t   ON s.tenant_id   = t.id
LEFT JOIN `production-267908.analytics.d_users`     usr ON usr.external_id = s.owner_id
WHERE DATE(s._PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND p.name IN ('MOBILE_SDK', 'MOBILE_FLOW_ANALYZER')
  AND t.name IS NOT NULL AND t.name != ''
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY scans DESC
LIMIT 5000
"""

print("Querying BigQuery…")
rows = list(client.query(QUERY).result())
print(f"Got {len(rows)} rows")

normalized = []
for r in rows:
    email = r["email"] if r["email"] and str(r["email"]).lower() not in ("null", "none", "") else None
    sa_id = r["serviceAccountId"] if r["serviceAccountId"] and str(r["serviceAccountId"]).lower() not in ("null", "none", "") else None

    # For MFA, sdk_type is NULL — use productName to identify it
    sdk_type = r["sdkType"] or r["productName"] or ""

    normalized.append({
        "tenantName":       r["tenantName"] or "",
        "email":            email,
        "serviceAccountId": sa_id,
        "sdkType":          sdk_type,
        "sdkVariant":       None,   # not available in BigQuery
        "sdkVersion":       "",   # not available in BigQuery scan_success
        "platformName":     r["platformName"] or "",
        "date":             str(r["date"]) if r["date"] else None,
        "scans":            int(r["scans"] or 0),
        "total_issues":     0,   # not available in BigQuery
        "critical_issues":  0,   # not available in BigQuery
    })

sdk = [r for r in normalized if r["sdkType"] != "MOBILE_FLOW_ANALYZER"]
mfa = [r for r in normalized if r["sdkType"] == "MOBILE_FLOW_ANALYZER"]
print(f"SDK rows: {len(sdk)}, with email: {sum(1 for r in sdk if r['email'])}, with SA: {sum(1 for r in sdk if r['serviceAccountId'])}")
print(f"MFA rows: {len(mfa)}, with email: {sum(1 for r in mfa if r['email'])}, with SA: {sum(1 for r in mfa if r['serviceAccountId'])}")

out = os.path.join(BASE, "rows_with_sa.json")
with open(out, "w") as f:
    json.dump(normalized, f)
print(f"Saved to {out}")

# ── 90-day daily aggregated rows (for charts) ─────────────────────────────────
QUERY_90D = """
SELECT
  DATE(s._PARTITIONTIME)       AS date,
  t.name                       AS tenantName,
  COALESCE(sd.type, p.name)    AS sdkType,
  s.os_name                    AS platformName,
  COUNT(*)                     AS scans
FROM `production-267908.analytics.scan_success` s
LEFT JOIN `production-267908.analytics.d_sdk_types` sd  ON s.sdk_type    = sd.id
LEFT JOIN `production-267908.analytics.d_products`  p   ON p.id          = s.product_name
LEFT JOIN `production-267908.analytics.tenants`     t   ON s.tenant_id   = t.id
WHERE DATE(s._PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  AND p.name IN ('MOBILE_SDK', 'MOBILE_FLOW_ANALYZER')
  AND t.name IS NOT NULL AND t.name != ''
GROUP BY 1, 2, 3, 4
ORDER BY date, tenantName
"""

print("Querying BigQuery (90-day daily)…")
rows_90d = list(client.query(QUERY_90D).result())
print(f"Got {len(rows_90d)} daily rows (90d)")

daily_normalized = []
for r in rows_90d:
    daily_normalized.append({
        "date":        str(r["date"]) if r["date"] else None,
        "tenantName":  r["tenantName"] or "",
        "sdkType":     r["sdkType"] or "",
        "platformName": r["platformName"] or "",
        "scans":       int(r["scans"] or 0),
    })

out_90d = os.path.join(BASE, "daily_rows_90d.json")
with open(out_90d, "w") as f:
    json.dump(daily_normalized, f)
print(f"Saved to {out_90d}")
