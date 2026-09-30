"""One-time, bounded Instagram batch test; no publishing or scheduled run."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
import requests

BASE = Path(__file__).resolve().parent
DATASET_ID = "gd_lk5ns7kz21pck8jpis"
LIMIT = 15
MEDIA_KNOWN = {
    "lofficielkorea", "voguekorea", "pap_magazine", "noblessekorea",
    "luxuryeditors", "allurekorea", "mensfoliomy", "voguephilippines",
    "dailyfashion_news", "marieclairekorea", "lofficielmy",
    "harpersbazaarjapan", "ellekorea",
}

def shortcode(url):
    try:
        p = urlparse(url)
        if p.hostname not in {"instagram.com", "www.instagram.com"}:
            return None
        m = re.fullmatch(r"/(?:p|reel|tv)/([A-Za-z0-9_-]{5,})/?",p.path)
        return m.group(1) if m else None
    except (ValueError, TypeError):
        return None

def dump(name, data):
    (BASE/name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

with (BASE/"candidates.json").open(encoding="utf-8") as f:
    urls = json.load(f).get("post_urls", [])
with (BASE/"known_posts.json").open(encoding="utf-8") as f:
    old = json.load(f)
known = {r.get("shortcode") or shortcode(r.get("post_url", "")) for r in old}
known.discard(None)

new = {}
for url in urls:
    code = shortcode(url)
    if code and code not in known:
        # Prefer /reel/ when the same shortcode appears in /p/ and /reel/.
        if code not in new or "/reel/" in url:
            new[code] = url
picked = list(new.values())[:LIMIT]
print(f"Candidates={len(urls)}, unique new={len(new)}, selected={len(picked)}")
dump("batch-plan.json", {"candidate_count":len(urls),"previously_collected":len(known),
                         "new_unique_count":len(new),"selected_urls":picked})
dump("media-review.json", [])
if not picked:
    print("No new posts. Skipping Bright Data request.")
    raise SystemExit(0)

key = os.environ.get("BRIGHTDATA_API_KEY")
if not key:
    raise RuntimeError("BRIGHTDATA_API_KEY secret not set")
res = requests.post(
    "https://api.brightdata.com/datasets/v3/scrape",
    params={"dataset_id": DATASET_ID, "notify": "false", "include_errors": "true"},
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json={"input":[{"url":u,"country":""} for u in picked],"limit_per_input":None},
    timeout=180,
)
print("HTTP:",res.status_code, "bytes:",len(res.content), "Content-Type:",res.headers.get("Content-Type"))
res.raise_for_status()
try:
    payload = res.json()
except ValueError:
    payload = [json.loads(line) for line in res.text.splitlines() if line.strip()]
if isinstance(payload, dict):
    print("Received a job/response object with keys:",list(payload))
    dump("batch-response-metadata.json",payload)
    raise SystemExit(0)
if not isinstance(payload, list):
    raise ValueError("Unexpected response shape")

rows=[]
for item in payload:
    if not isinstance(item,dict):
        continue
    url=item.get("url") or (item.get("input") or {}).get("url", "")
    account=(item.get("user_posted") or "").strip().lower()
    desc=item.get("description") or ""
    # The fan/media determination isn't reliable from keywords alone.
    status="known_media_candidate" if account in MEDIA_KNOWN else "needs_manual_review"
    if account=="for_everyoung10": status="exclude_artist_own_account"
    rows.append({
        "url":url,"shortcode":item.get("shortcode") or shortcode(url),
        "account":account,"date_posted":item.get("date_posted"),
        "caption":desc[:2500], "likes":item.get("likes"),
        "comments":item.get("num_comments"),"review_status":status,
        "error":str(item.get("error") or "")[:250]
    })
dump("media-review.json",rows)
print("Returned:",len(payload),"review records:",len(rows))
print("Needs manual review:",sum(r["review_status"]=="needs_manual_review" for r in rows))
print("No website files were modified.")
