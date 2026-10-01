from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CUTOFF_DATE = "2026-09-27"

PERSON_TERMS = (
    "wonyoung", "jang wonyoung", "장원영", "원영",
    "ウォニョン", "张元英", "張員瑛", "for_everyoung10",
)
DIOR_TERMS = ("dior", "디올", "ディオール", "迪奥", "迪奧")

# Strong enough for unknown accounts to remain AUTO.
# Generic words such as "fashion", "style", "trend", "daily" are intentionally excluded.
STRONG_MEDIA_HINTS = (
    "magazine", "news", "vogue", "elle", "bazaar", "harpers",
    "marieclaire", "lofficiel", "cosmopolitan", "allure", "wwd",
    "dazed", "grazia", "hypebeast", "hypebae", "editorial",
    "gq", "esquire", "numero", "nylon", "buro", "prestige",
    "tatler", "herworld", "mensuno", "mensfolio", "fashionsnap",
)

def load(name, fallback):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else fallback

def save(name, obj):
    (ROOT / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

def relevant(caption):
    s = str(caption or "").casefold()
    return (
        any(x.casefold() in s for x in PERSON_TERMS)
        and any(x.casefold() in s for x in DIOR_TERMS)
    )

def strong_media_like(account, trusted):
    a = str(account or "").strip().lower()
    return a in trusted or any(h in a for h in STRONG_MEDIA_HINTS)

def main():
    posts = load("posts.json", {"posts": []})
    queue = load("media-review-queue.json", [])
    trust_file = load("trusted_media.json", {})
    trusted = {str(x).lower() for x in trust_file.get("accounts", [])}
    excluded = {str(x).lower() for x in trust_file.get("excluded_accounts", [])}

    public = list(posts.get("posts", []))
    cleaned = []
    removed = 0

    # Keep manually reviewed content. For AUTO rows, require a trusted account
    # or a strong media-name signal. This removes generic/fan-looking false positives.
    for row in public:
        account = str(row.get("account") or "").lower()
        source = str(row.get("source") or "")
        auto_row = source in {"brightdata_auto", "queue_auto_promoted"} or row.get("review_status") == "auto_discovered"
        if auto_row and (account in excluded or not strong_media_like(account, trusted)):
            removed += 1
            continue
        cleaned.append(row)

    public_ids = {str(x.get("id")) for x in cleaned if x.get("id")}
    new_queue = []
    promoted = 0

    # Promote only NEW V2/V3 scraper rows that were previously blocked solely
    # because the account had not yet been on the allowlist.
    # Legacy / mismatched-link records are intentionally NOT promoted here.
    for item in queue:
        ident = str(item.get("id") or "")
        account = str(item.get("account") or "").lower()
        modern_scrape = bool(item.get("last_checked_at"))
        promotable_reason = item.get("review_reason") == "not_media_like"
        recent = not item.get("date") or str(item.get("date"))[:10] >= CUTOFF_DATE

        if (
            ident and ident not in public_ids
            and modern_scrape
            and promotable_reason
            and recent
            and account in trusted
            and account not in excluded
            and relevant(item.get("caption"))
        ):
            row = dict(item)
            row["review_status"] = "auto_discovered"
            row["source"] = "queue_auto_promoted"
            row.pop("review_reason", None)
            cleaned.append(row)
            public_ids.add(ident)
            promoted += 1
        else:
            new_queue.append(item)

    cleaned.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    posts["posts"] = cleaned

    save("posts.json", posts)
    save("media-review-queue.json", new_queue)

    report = load("last-run.json", {})
    report["post_filter_removed_false_positive"] = removed
    report["post_filter_promoted_from_queue"] = promoted
    report["public_total_after_filter"] = len(cleaned)
    save("last-run.json", report)

    print(
        "Post filter complete.",
        "removed false positives:", removed,
        "promoted from trusted queue:", promoted,
        "public total:", len(cleaned),
    )

if __name__ == "__main__":
    main()
