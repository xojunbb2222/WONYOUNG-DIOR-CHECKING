"""Bounded media discovery for WONYOUNG × DIOR. Uses the already configured Bright Data SERP zone and IG post dataset.

Explicit safety choices: account allowlist is not independent account verification;
unknown/ambiguous/wrong URL results are queued, not published. No user token is ever written to files.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
SERP_ZONE = "serp_api1"
IG_DATASET = "gd_lk5ns7kz21pck8jpis"
# 2 SERP requests + no more than 8 Instagram post lookups per run.
SEARCH_CALLS = 2
SCRAPE_LIMIT = 8
MAX_ROWS = 1500

QUERIES = [
    'site:instagram.com "Wonyoung" "DiorSummer27"',
    'site:instagram.com "장원영" "디올" "쇼"',
    'site:instagram.com "ウォニョン" "ディオール"',
    'site:instagram.com "张元英" "迪奥"',
    'site:instagram.com "Jang Wonyoung" "Dior" "Paris"',
    'site:instagram.com "Wonyoung" "Dior" "fashion week"',
    'site:instagram.com "원영" "Dior" "2027"',
    'site:instagram.com "Wonyoung" "Dior" "Vogue"',
]
TERMS_WONYOUNG = ["wonyoung", "jang wonyoung", "장원영", "원영", "ウォニョン", "张元英", "張員瑛", "for_everyoung10"]
TERMS_DIOR = ["dior", "디올", "ディオール", "迪奥", "迪奧"]
POST_REGEX = re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]{5,})', re.I)


def load(name, fallback):
    path = ROOT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def shortcode(url):
    if not isinstance(url, str):
        return None
    try:
        u = urllib.parse.urlparse(html.unescape(url).replace('\\/', '/'))
        if u.hostname not in ("www.instagram.com", "instagram.com"):
            return None
        m = re.fullmatch(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?', u.path, re.I)
        return m.group(1) if m else None
    except ValueError:
        return None


def normalized_url(url):
    code = shortcode(url)
    if not code:
        return None
    m = re.search(r'instagram\.com/(p|reel|reels|tv)/', url, re.I)
    typ = 'p' if m.group(1).lower() == 'p' else 'reel'
    return f'https://www.instagram.com/{typ}/{code}/'


def discovered_urls(document):
    """Collect result hrefs (not arbitrary Instagram links buried in JS/text).

    Google /url?q redirects are supported. SEO snippets aren't treated as proof of publication.
    """
    soup = BeautifulSoup(document, 'html.parser')
    urls = set()
    for anchor in soup.find_all('a', href=True):
        href = html.unescape(anchor.get('href', ''))
        if href.startswith('/url?'):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
            href = (params.get('q') or params.get('url') or [''])[0]
        for _ in range(2):
            href = urllib.parse.unquote(href)
        candidate = normalized_url(href)
        if candidate:
            urls.add(candidate)
    return urls


def relevant(caption):
    s = str(caption or '').casefold()
    return any(t.casefold() in s for t in TERMS_WONYOUNG) and any(t.casefold() in s for t in TERMS_DIOR)


def request_serp(key, query):
    url = 'https://www.google.com/search?q=' + urllib.parse.quote(query)
    result = requests.post(
        'https://api.brightdata.com/request',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={'zone': SERP_ZONE, 'url': url, 'format': 'raw'}, timeout=120)
    result.raise_for_status()
    return discovered_urls(result.text)


def request_posts(key, urls):
    res = requests.post(
        'https://api.brightdata.com/datasets/v3/scrape',
        params={'dataset_id': IG_DATASET, 'notify': 'false', 'include_errors': 'true'},
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={'input': [{'url': url, 'country': ''} for url in urls], 'limit_per_input': None},
        timeout=180)
    res.raise_for_status()
    try:
        value = res.json()
    except ValueError:
        value = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    # Bright Data sometimes returns a snapshot_id instead of synchronous records.
    if isinstance(value, dict):
        print('Async response received; no posts published. Metadata keys:', list(value))
        save('last-run.json', {'result': 'snapshot_pending', 'snapshot_id': value.get('snapshot_id')})
        return []
    if not isinstance(value, list):
        raise ValueError('Unexpected IG response type')
    return value



def verify_original_post(url, expected_account):
    """Independent public-page verification; blocked/ambiguous pages FAIL CLOSED.

    We do NOT treat Bright Data's returned account or SERP snippet as proof.
    """
    code = shortcode(url)
    if not code or not expected_account:
        return False, 'invalid_url_or_account'
    # Try the permalink first, then Instagram's public embed for a separate source.
    for path in (url, url.rstrip('/') + '/embed/captioned/'):
        try:
            res = requests.get(path, timeout=16, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; MediaChecking/1.0)'})
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, 'html.parser')
            candidates = []
            for key in ('og:title', 'twitter:title'):
                meta = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
                if meta:
                    candidates.append(meta.get('content', ''))
            if soup.title:
                candidates.append(soup.title.get_text(' ', strip=True))
            # An account name in visible caption text does not prove authorship.
            # Require a title explicitly formatted as a named Instagram author.
            pattern = re.compile(r'(?:^|\s|@)' + re.escape(expected_account) +
                                 r'\s+(?:on Instagram|• Instagram|\(@)', re.I)
            title_match = any(pattern.search(t) for t in candidates)
            # Even with an author-looking title, verify same shortcode is present in
            # page URL metadata or the resolved URL. Instagram login wall is not valid.
            canonical = soup.find('link', rel='canonical')
            ogurl = soup.find('meta', attrs={'property':'og:url'})
            source_urls = [res.url]
            if canonical: source_urls.append(canonical.get('href', ''))
            if ogurl: source_urls.append(ogurl.get('content', ''))
            same_post = any(shortcode(u) == code for u in source_urls)
            if title_match and same_post:
                return True, 'matched_independent_instagram_metadata'
        except requests.RequestException:
            pass
    return False, 'instagram_public_verification_unavailable_or_mismatch'


def main():
    key = os.environ.get('BRIGHTDATA_API_KEY', '')
    if not key:
        sys.exit('Missing BRIGHTDATA_API_KEY secret; no requests sent')
    state = load('media-state.json', {'search_cursor': 0, 'seen': []})
    existing = load('posts.json', {'posts': []})
    review = load('media-review-queue.json', [])
    allow = load('trusted_media.json', {})
    trusted = {x.lower() for x in allow.get('accounts', [])}
    excluded = {x.lower() for x in allow.get('excluded_accounts', [])}
    seen = set(state.get('seen', []))
    # Treat all published posts as seen. Manually curated links can be retained.
    for p in existing.get('posts', []):
        seen.add(str(p.get('id') or shortcode(p.get('url')) or ''))
    for p in review:
        seen.add(str(p.get('id') or shortcode(p.get('url')) or ''))
    new_links = {}
    cursor = int(state.get('search_cursor', 0))
    for offset in range(SEARCH_CALLS):
        query = QUERIES[(cursor + offset) % len(QUERIES)]
        try:
            results = request_serp(key, query)
            print('SERP', query, 'links:', len(results))
            for url in results:
                code = shortcode(url)
                if code and code not in seen:
                    new_links.setdefault(code, url)
        except requests.RequestException as exc:
            print('SERP failed:', type(exc).__name__)
    state['search_cursor'] = (cursor + SEARCH_CALLS) % len(QUERIES)
    picks = list(new_links.values())[:SCRAPE_LIMIT]
    print('New unique discovered:', len(new_links), 'selected:', len(picks))
    rows = []
    scrape_success = False
    if picks:
        try:
            rows = request_posts(key, picks)
            scrape_success = bool(rows)
        except (requests.RequestException, ValueError) as exc:
            print('IG request failed:', type(exc).__name__)
            # Do not mark posts as seen on a failed request: retry on next run.
    requested = {shortcode(url): url for url in picks}
    pending = {str(p.get('id')) for p in review}
    published = {str(p.get('id')) for p in existing.get('posts', [])}
    added = 0
    quarantined = 0
    for record in rows:
        if not isinstance(record, dict):
            continue
        raw_url = record.get('url') or ''
        ident = shortcode(raw_url)
        if not ident or ident not in requested:
            # Never assign an unrelated search result to the requested URL.
            print('Reject: scraper returned unexpected URL', str(raw_url)[:120])
            continue
        if ident in published or ident in pending:
            continue
        account = str(record.get('user_posted') or '').strip().lstrip('@').lower()
        caption = str(record.get('description') or '').strip()
        item = {
            'id': ident, 'account': account, 'url': requested[ident],
            'date': str(record.get('date_posted') or ''), 'caption': caption[:1500],
            'review_status': 'unverified',
        }
        # Two sources must agree on the exact account and post ID before publication:
        # Bright Data metadata + independently fetched Instagram page metadata.
        if account in trusted and account not in excluded and relevant(caption):
            verified, proof = verify_original_post(item['url'], account)
            if verified:
                item['review_status'] = 'source_verified'
                item['verification'] = proof
                existing.setdefault('posts', []).append(item)
                published.add(ident)
                seen.add(ident)
                added += 1
                continue
            reason = proof
        else:
            reason = ('artist_or_fan_account' if account in excluded else
                      'unlisted_account' if account not in trusted else
                      'not_about_wonyoung_dior')
        item['review_reason'] = reason
        review.append(item)
        pending.add(ident)
        seen.add(ident)
        quarantined += 1
    # Keep an audit entry for mismatched scraper outputs. Never retry them forever
    # on paid APIs when we received a completed response but no matching post.
    if scrape_success:
        for ident, url in requested.items():
            if ident not in seen:
                review.append({'id': ident, 'url': url, 'account': '', 'date': '',
                               'caption': '', 'review_status': 'unverified',
                               'review_reason': 'no_matching_scraper_record'})
                seen.add(ident)
                quarantined += 1
    # Do not retroactively promote unverified legacy posts. Preserve human-approved entries only.
    existing['posts'] = existing.get('posts', [])[-MAX_ROWS:]
    review = review[-MAX_ROWS:]
    save('media-state.json', {'search_cursor': state['search_cursor'], 'seen': sorted(x for x in seen if x)[-10000:]})
    save('media-review-queue.json', review)
    save('posts.json', existing)
    save('last-run.json', {
        'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'queries_used': SEARCH_CALLS, 'selected': len(picks), 'returned': len(rows),
        'published': added, 'needs_review': quarantined,
        'note': 'Public publishing only when independent Instagram metadata confirms post ID and known media account; otherwise queued.'
    })
    print('Finished. Media candidates queued:', quarantined, 'public additions:', added)


if __name__ == '__main__':
    main()
