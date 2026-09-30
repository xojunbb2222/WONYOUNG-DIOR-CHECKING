"""Two-input diagnostic, not a publishing or monitoring tool.

Only sends two URLs to the existing Bright Data Instagram Posts dataset.
Never exports credentials or updates Checking data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent
DATASET_ID = "gd_lk5ns7kz21pck8jpis"
SAMPLES = [
    {
        "name": "user_supplied_reference",
        "url": "https://www.instagram.com/p/Dd6WW5Lk-6w/?img_index=1",
        "note": "User-supplied comparison reference; account not pre-assumed",
    },
    {
        "name": "reported_broken_candidate",
        "url": "https://www.instagram.com/reel/Dd347fCMAsJ/",
        "expected_account_from_old_list": "mensfoliomy",
    },
]
SHORTCODE = re.compile(r"^/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?$", re.I)


def code(url):
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if parts.hostname not in ("www.instagram.com", "instagram.com"):
        return None
    m = SHORTCODE.fullmatch(parts.path)
    return m.group(1) if m else None


def interpret(payload):
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return payload["data"], None
        if isinstance(payload.get("results"), list):
            return payload["results"], None
        if payload.get("snapshot_id"):
            return [], {"kind": "async_snapshot", "note": "Provider returned a snapshot_id. Do not assume scrape completed.", "snapshot_id": payload["snapshot_id"]}
        return [], {"kind": "unexpected_object", "keys": sorted(payload.keys())[:15]}
    raise ValueError(f"Unexpected response type: {type(payload).__name__}")


def write_report(report):
    path = ROOT / "source-diagnostic.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved source-diagnostic.json")


def build_report(records, provider_info):
    target = {code(s["url"]): s for s in SAMPLES}
    rows = []
    returned_codes = set()
    for r in records:
        if not isinstance(r, dict):
            continue
        returned_url = r.get("url")
        returned_code = code(returned_url)
        returned_codes.add(returned_code)
        matching = target.get(returned_code)
        rows.append({
            "returned_url": returned_url,
            "returned_shortcode": returned_code,
            "matching_requested_sample": matching["name"] if matching else None,
            "user_posted_from_dataset": r.get("user_posted"),
            "posted_at_from_dataset": r.get("date_posted"),
            "caption_excerpt_from_dataset": str(r.get("description") or "")[:180],
            "scraper_error": str(r.get("error") or "")[:180],
        })
    status = []
    for s in SAMPLES:
        found = [r for r in rows if r["returned_shortcode"] == code(s["url"])]
        status.append({"sample": s["name"], "requested_url": s["url"],
                       "requested_shortcode": code(s["url"]),
                       "returned_matching_shortcode": bool(found),
                       "matching_record_count": len(found),
                       "expected_account_from_old_list": s.get("expected_account_from_old_list")})
    return {
        "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "Compare provider response IDs for a user-supplied reference and one reported broken URL. This does NOT independently validate Instagram authorship.",
        "provider": provider_info,
        "samples": status, "records": rows,
        "note": "Do not publish based on this report alone; the actual Instagram permalink must be verified against the account's own post listing or another independent source.",
    }


def main():
    key = os.environ.get("BRIGHTDATA_API_KEY")
    if not key:
        raise RuntimeError("Missing BRIGHTDATA_API_KEY secret. No request sent.")
    report = {"result": "not_started"}
    try:
        response = requests.post(
            "https://api.brightdata.com/datasets/v3/scrape",
            params={"dataset_id": DATASET_ID, "notify": "false", "include_errors": "true"},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"input": [{"url": s["url"], "country": ""} for s in SAMPLES], "limit_per_input": None},
            timeout=180,
        )
        print("HTTP:", response.status_code, "bytes:", len(response.content))
        provider = {"http": response.status_code, "response_bytes": len(response.content),
                    "content_type": response.headers.get("Content-Type", "")}
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        records, pending = interpret(payload)
        if pending:
            report = {"time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "purpose": "Two-URL Instagram scrape comparison", "provider": provider,
                      "pending": pending, "warning": "No synchronous records were available."}
        else:
            report = build_report(records, provider)
            print("Records:", len(report["records"]),
                  "matching reference:", report["samples"][0]["returned_matching_shortcode"],
                  "matching broken candidate:", report["samples"][1]["returned_matching_shortcode"])
    except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
        report = {"time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "result": "error", "error_class": type(e).__name__,
                  "details": "Provider response failed or could not be parsed; inspect GitHub logs. No Checking changes."}
        print("Diagnostic failed:", type(e).__name__)
    write_report(report)


if __name__ == "__main__":
    main()
