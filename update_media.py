"""WONYOUNG × DIOR live Instagram media collector.

Goals:
- discover new Instagram coverage automatically;
- handle Bright Data synchronous requests that fall back to snapshot jobs;
- publish high-confidence media coverage to posts.json automatically;
- keep lower-confidence results in media-review-queue.json;
- refresh engagement metrics for recent public posts.

Auto-published rows are labeled auto_discovered, not manually verified.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
ZONE = "serp_api1"
IG_POST_DATASET = "gd_lk5ns7kz21pck8jpis"
SEARCH_CALLS = 4
MAX_NEW_SCRAPES = 14
REFRESH_EXISTING = 6
MAX_ROWS = 1500
CUTOFF_DATE = "2026-09-27"

QUERIES = [
    'site:instagram.com "Wonyoung" "DiorSummer27"',
    'site:instagram.com "Jang Wonyoung" "Dior" "Paris Fashion Week"',
    'site:instagram.com "장원영" "디올" "패션위크"',
    'site:instagram.com "ウォニョン" "ディオール"',
    'site:instagram.com "张元英" "迪奥"',
    'site:instagram.com "張員瑛" "Dior"',
    'site:instagram.com "Wonyoung" "Dior" "Vogue"',
    'site:instagram.com "Wonyoung" "Dior" "fashion"',
]

PERSON_TERMS = (
    "wonyoung", "jang wonyoung", "장원영", "원영", "ウォニョン",
    "张元英", "張員瑛", "for_everyoung10",
)
DIOR_TERMS = ("dior", "디올", "ディオール", "迪奥", "迪奧")

MEDIA_HINTS = (
    "vogue", "elle", "bazaar", "harpers", "marieclaire", "lofficiel",
    "cosmopolitan", "allure", "wwd", "dazed", "grazia", "fashion",
    "magazine", "style", "news", "pap", "luxury", "folio", "snap",
    "hype", "editorial", "daily", "media", "gq", "esquire", "numero",
    "nylon", "buro", "prestige", "tatler", "herworld", "mensuno",
    "mensfolio", "celeb", "trend",
)
BLOCK_ACCOUNT_EXACT = {
    "for_everyoung10", "ivestarship", "dior", "wonyoungdollz",
    "jwonyoungallery", "ivearemyults",
}
BLOCK_ACCOUNT_PARTS = (
    "wonyoungfan", "wonyoung_fan", "wonyoungupdate", "wonyoung_update",
    "wonyounggallery", "wonyoung_gallery", "wonyoungdoll", "iveupdate",
    "ive_update", "blackpinkupdate", "blackpink_update", "fanbase",
    "fansite", "fanpage",
)

LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]{5,})",
    re.I,
)


def load(name, fallback):
    path = ROOT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback


def save(name, obj):
    (ROOT / name).write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def shortcode(url):
    if not isinstance(url, str):
        return None
    try:
        p = urllib.parse.urlparse(html.unescape(url).replace("\\/", "/"))
    except ValueError:
        return None
    if p.hostname not in ("instagram.com", "www.instagram.com"):
        return None
    m = re.fullmatch(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?", p.path, re.I)
    return m.group(1) if m else None


def stable_post_url(ident):
    # /p/<shortcode>/ proved more stable for this project than some discovered /reel/ links.
    return f"https://www.instagram.com/p/{ident}/"


def normalized_url(url):
    ident = shortcode(url)
    return stable_post_url(ident) if ident else None


def links_from_text(s):
    if not isinstance(s, str):
        return set()
    s = (
        html.unescape(s)
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u003A", ":")
        .replace("\\u0026", "&")
    )
    for _ in range(2):
        s = urllib.parse.unquote(s)
    found = set()
    for match in LINK_RE.finditer(s):
        found.add(stable_post_url(match.group(2)))
    for anchor in BeautifulSoup(s, "html.parser").find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("/url?"):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
            href = (qs.get("q") or qs.get("url") or [""])[0]
        u = normalized_url(href)
        if u:
            found.add(u)
    return found


def links_from_tree(payload):
    found, seen_nodes = set(), 0

    def walk(value, depth=0):
        nonlocal seen_nodes
        if depth > 12 or seen_nodes >= 12000:
            return
        seen_nodes += 1
        if isinstance(value, str):
            found.update(links_from_text(value))
            if value[:1] in ("{", "["):
                try:
                    walk(json.loads(value), depth + 1)
                except ValueError:
                    pass
        elif isinstance(value, list):
            for item in value[:2500]:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in ("authorization", "api_key", "token"):
                    continue
                walk(item, depth + 1)

    walk(payload)
    return found


def request_serp(key, query):
    # Recent-only Google results reduce stale hits and speed up useful discovery.
    google = "https://www.google.com/search?" + urllib.parse.urlencode(
        {"q": query, "tbs": "qdr:d", "filter": "0"}
    )
    res = requests.post(
        "https://api.brightdata.com/request",
        timeout=120,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"zone": ZONE, "url": google, "format": "json", "data_format": "parsed_light"},
    )
    print("SERP transport HTTP:", res.status_code, "bytes:", len(res.content))
    res.raise_for_status()
    if not res.content.strip():
        return set()
    try:
        wrapper = res.json()
    except ValueError:
        return links_from_text(res.text)
    if isinstance(wrapper, dict) and wrapper.get("status_code"):
        try:
            if int(wrapper["status_code"]) >= 400:
                return set()
        except (ValueError, TypeError):
            pass
    body = wrapper.get("body", wrapper) if isinstance(wrapper, dict) else wrapper
    found = links_from_tree(body)
    print("SERP candidate URLs:", len(found))
    return found


def parse_json_response(res):
    if not res.content.strip():
        return None
    try:
        return res.json()
    except ValueError:
        rows = []
        for line in res.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows if rows else None


def wait_snapshot(key, snapshot_id, timeout=300):
    headers = {"Authorization": f"Bearer {key}"}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(
            f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}",
            headers=headers,
            timeout=45,
        )
        r.raise_for_status()
        status_obj = r.json()
        status = str(status_obj.get("status") or "").lower()
        if status != last:
            print("Snapshot", snapshot_id, "status:", status)
            last = status
        if status == "ready":
            out = requests.get(
                f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
                params={"format": "json"},
                headers=headers,
                timeout=120,
            )
            out.raise_for_status()
            obj = parse_json_response(out)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                return [obj]
            return []
        if status == "failed":
            print("Snapshot failed:", status_obj)
            return []
        time.sleep(8)
    print("Snapshot timed out:", snapshot_id)
    return []


def request_posts(key, urls):
    if not urls:
        return []
    payload = [{"url": u} for u in urls]
    res = requests.post(
        "https://api.brightdata.com/datasets/v3/scrape",
        params={"dataset_id": IG_POST_DATASET, "include_errors": "true", "format": "json"},
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    print("Instagram scrape HTTP:", res.status_code)
    if res.status_code not in (200, 202):
        res.raise_for_status()
    obj = parse_json_response(res)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        snapshot_id = obj.get("snapshot_id")
        if snapshot_id:
            print("Sync scrape fell back to snapshot:", snapshot_id)
            return wait_snapshot(key, snapshot_id)
        # A single-record JSON response is also valid.
        if obj.get("url") or obj.get("shortcode"):
            return [obj]
    return []


def relevant(caption):
    s = str(caption or "").casefold()
    return any(x.casefold() in s for x in PERSON_TERMS) and any(
        x.casefold() in s for x in DIOR_TERMS
    )


def possible_visual_event(caption):
    s = str(caption or "").casefold()
    if "diorsummer27" in s or "dior27ss" in s:
        return True
    return any(x.casefold() in s for x in DIOR_TERMS) and any(
        t in s
        for t in (
            "ss27", "2027", "fashion week", "runway", "fashion show",
            "时装周", "패션위크", "パリコレ", "秀场", "쇼장",
        )
    )


def media_like(account, trusted):
    a = str(account or "").lower().strip()
    if not a or a in BLOCK_ACCOUNT_EXACT:
        return False
    if any(x in a for x in BLOCK_ACCOUNT_PARTS):
        return False
    if a in trusted:
        return True
    return any(hint in a for hint in MEDIA_HINTS)


def clean_number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def metrics_from(record):
    return {
        "likes": clean_number(record.get("likes") or record.get("likes_count")),
        "comments": clean_number(record.get("num_comments") or record.get("comments_count")),
        "views": clean_number(
            record.get("video_play_count") or record.get("views") or record.get("play_count")
        ),
    }


def main():
    key = os.environ.get("BRIGHTDATA_API_KEY")
    if not key:
        raise RuntimeError("BRIGHTDATA_API_KEY is not configured")

    state = load("media-state.json", {"search_cursor": 0, "seen": []})
    posts = load("posts.json", {"posts": []})
    review = load("media-review-queue.json", [])
    allowed = load("trusted_media.json", {})
    trusted = {str(a).lower() for a in allowed.get("accounts", [])}
    excluded = {str(a).lower() for a in allowed.get("excluded_accounts", [])}

    public_rows = posts.setdefault("posts", [])
    public_by_id = {str(x.get("id")): x for x in public_rows if isinstance(x, dict) and x.get("id")}
    pending_ids = {str(x.get("id")) for x in review if isinstance(x, dict) and x.get("id")}
    seen = set(str(x) for x in state.get("seen", []) if x)
    seen.update(public_by_id)
    seen.update(pending_ids)

    cursor = int(state.get("search_cursor", 0))
    discovered = {}
    for offset in range(SEARCH_CALLS):
        query_index = (cursor + offset) % len(QUERIES)
        query = QUERIES[query_index]
        try:
            urls = request_serp(key, query)
            print("SERP query index:", query_index, "results:", len(urls))
            for url in sorted(urls):
                ident = shortcode(url)
                if ident and ident not in seen:
                    discovered.setdefault(ident, stable_post_url(ident))
        except requests.RequestException as exc:
            print("SERP transport failed:", type(exc).__name__)

    state["search_cursor"] = (cursor + SEARCH_CALLS) % len(QUERIES)
    new_urls = list(discovered.values())[:MAX_NEW_SCRAPES]

    # Refresh engagement on the most recent public rows in the same request budget.
    recent_rows = sorted(public_rows, key=lambda x: str(x.get("date") or ""), reverse=True)
    refresh_urls = []
    for row in recent_rows:
        ident = str(row.get("id") or "")
        if ident and ident not in discovered:
            refresh_urls.append(stable_post_url(ident))
        if len(refresh_urls) >= REFRESH_EXISTING:
            break

    requested_urls = (new_urls + refresh_urls)[:20]
    requested = {shortcode(u): u for u in requested_urls if shortcode(u)}
    print(
        "New unique discovered:", len(discovered),
        "new selected:", len(new_urls),
        "refresh selected:", len(refresh_urls),
        "total scrape inputs:", len(requested_urls),
    )

    records = []
    if requested_urls:
        try:
            records = request_posts(key, requested_urls)
        except (requests.RequestException, ValueError) as exc:
            print("IG scrape failed:", type(exc).__name__, str(exc)[:180])

    auto_published = queued = refreshed = 0
    returned_ids = set()
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for record in records:
        if not isinstance(record, dict):
            continue
        ident = str(record.get("shortcode") or shortcode(record.get("url") or "") or "")
        if not ident or ident not in requested:
            print("Skipped mismatched scraper row")
            continue
        returned_ids.add(ident)
        account = str(record.get("user_posted") or record.get("user_name") or "").strip().lstrip("@").lower()
        caption = str(record.get("description") or record.get("caption") or "").strip()
        date = str(record.get("date_posted") or record.get("date") or "")
        metrics = metrics_from(record)

        # Existing public row: only refresh metrics and freshness metadata.
        if ident in public_by_id:
            row = public_by_id[ident]
            row.update(metrics)
            row["last_checked_at"] = now
            refreshed += 1
            continue

        if ident in pending_ids:
            continue

        item = {
            "id": ident,
            "account": account,
            "url": stable_post_url(ident),
            "discovered_url": requested[ident],
            "date": date,
            "caption": caption[:1800],
            **metrics,
            "last_checked_at": now,
        }

        account_blocked = account in excluded or account in BLOCK_ACCOUNT_EXACT
        recent_enough = not date or date[:10] >= CUTOFF_DATE
        if (
            not account_blocked
            and recent_enough
            and relevant(caption)
            and media_like(account, trusted)
        ):
            item.update({
                "review_status": "auto_discovered",
                "source": "brightdata_auto",
            })
            public_rows.append(item)
            public_by_id[ident] = item
            auto_published += 1
            seen.add(ident)
        else:
            item.update({
                "review_status": "unverified",
                "review_reason": (
                    "excluded_account" if account_blocked else
                    "not_media_like" if not media_like(account, trusted) else
                    "possible_visual_mention_requires_review" if possible_visual_event(caption) else
                    "missing_topics"
                ),
            })
            review.append(item)
            pending_ids.add(ident)
            queued += 1
            seen.add(ident)

    # Do NOT mark transiently missing scrape results as seen; retry them next run.
    missing_return = sorted(set(requested) - returned_ids)
    if missing_return:
        print("Inputs with no returned row (will retry if rediscovered):", len(missing_return))

    public_rows.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    posts["posts"] = public_rows[:MAX_ROWS]
    posts["updated_at"] = now
    posts["mode"] = "live_auto_media"
    review = review[-MAX_ROWS:]

    save("posts.json", posts)
    save("media-review-queue.json", review)
    save(
        "media-state.json",
        {
            "search_cursor": state["search_cursor"],
            "seen": sorted(x for x in seen if x)[-10000:],
        },
    )
    save(
        "last-run.json",
        {
            "time_utc": now,
            "queries_used": SEARCH_CALLS,
            "discovered_unique": len(discovered),
            "new_selected": len(new_urls),
            "refresh_selected": len(refresh_urls),
            "returned": len(records),
            "auto_published": auto_published,
            "queued_for_review": queued,
            "refreshed": refreshed,
            "retryable_missing": len(missing_return),
            "note": "High-confidence media rows publish automatically as AUTO; lower-confidence rows remain in review queue.",
        },
    )
    print(
        "Finished. auto published:", auto_published,
        "queued:", queued,
        "refreshed:", refreshed,
        "public total:", len(posts["posts"]),
    )


if __name__ == "__main__":
    main()
