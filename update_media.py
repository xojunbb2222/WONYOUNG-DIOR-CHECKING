"""Bounded, conservative WONYOUNG Dior Instagram-media collector.

Discovery is NOT proof of authorship. Unverified items are queued, not published.
Bright Data request secrets are never printed or saved.
"""
import datetime as dt
import html
import json
import os
import re
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
ZONE = 'serp_api1'
IG_DATASET = 'gd_lk5ns7kz21pck8jpis'
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
PERSON_TERMS = ('wonyoung', 'jang wonyoung', '장원영', '원영', 'ウォニョン', '张元英', '張員瑛', 'for_everyoung10')
DIOR_TERMS = ('dior', '디올', 'ディオール', '迪奥', '迪奧')
LINK_RE = re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]{5,})', re.I)


def load(name, fallback):
    path = ROOT / name
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else fallback


def save(name, obj):
    (ROOT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def shortcode(url):
    if not isinstance(url, str):
        return None
    try:
        p = urllib.parse.urlparse(html.unescape(url).replace('\\/', '/'))
    except ValueError:
        return None
    if p.hostname not in ('instagram.com', 'www.instagram.com'):
        return None
    m = re.fullmatch(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?', p.path, re.I)
    return m.group(1) if m else None


def normalized_url(url):
    code = shortcode(url)
    if not code:
        return None
    kind = 'p' if '/p/' in url.lower() else 'reel'
    return f'https://www.instagram.com/{kind}/{code}/'


def links_from_text(s):
    if not isinstance(s, str):
        return set()
    s = html.unescape(s).replace('\\/', '/').replace('\\u002F', '/').replace('\\u003A', ':').replace('\\u0026', '&')
    for _ in range(2):
        s = urllib.parse.unquote(s)
    found = set()
    for match in LINK_RE.finditer(s):
        kind = 'p' if match.group(0).lower().split('instagram.com/')[-1].startswith('p/') else 'reel'
        found.add(f'https://www.instagram.com/{kind}/{match.group(2)}/')
    # Search result links may be hosted as Google redirect anchors.
    for anchor in BeautifulSoup(s, 'html.parser').find_all('a', href=True):
        href = anchor['href']
        if href.startswith('/url?'):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
            href = (qs.get('q') or qs.get('url') or [''])[0]
        u = normalized_url(href)
        if u:
            found.add(u)
    return found


def links_from_tree(payload):
    """Read Bright Data JSON results without guessing a particular schema."""
    found, seen_nodes = set(), 0

    def walk(value, depth=0):
        nonlocal seen_nodes
        if depth > 12 or seen_nodes >= 10000:
            return
        seen_nodes += 1
        if isinstance(value, str):
            # Needed because Bright Data may JSON-encode the HTML or light JSON body.
            found.update(links_from_text(value))
            if value[:1] in ('{', '['):
                try:
                    inner = json.loads(value)
                except ValueError:
                    return
                walk(inner, depth + 1)
        elif isinstance(value, list):
            for item in value[:2000]:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in ('authorization', 'api_key', 'token'):
                    continue
                walk(item, depth + 1)
    walk(payload)
    return found


def request_serp(key, query):
    url = 'https://www.google.com/search?q=' + urllib.parse.quote(query)
    res = requests.post('https://api.brightdata.com/request', timeout=120,
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={'zone': ZONE, 'url': url, 'format': 'json', 'data_format': 'parsed_light'})
    print('SERP transport HTTP:', res.status_code, 'bytes:', len(res.content))
    res.raise_for_status()
    if not res.content.strip():
        print('SERP empty transport response')
        return set()
    try:
        wrapper = res.json()
    except ValueError:
        print('SERP payload not JSON; extracting unverified links from text')
        return links_from_text(res.text)
    if isinstance(wrapper, dict):
        print('SERP wrapper keys:', sorted(wrapper)[:15])
        if 'status_code' in wrapper:
            print('SERP upstream status_code:', wrapper['status_code'])
            try:
                upstream = int(wrapper['status_code'])
            except (ValueError, TypeError):
                upstream = 0
            if upstream and not 200 <= upstream < 300:
                print('SERP upstream unsuccessful; no links used')
                return set()
        body = wrapper.get('body', wrapper)
        print('SERP body type:', type(body).__name__,
              'length:', len(body) if isinstance(body, (str, list, dict)) else 0)
        if body is None or body == '' or body == []:
            print('SERP upstream returned empty body')
            return set()
        found = links_from_tree(body)
    else:
        print('SERP data type:', type(wrapper).__name__)
        found = links_from_tree(wrapper)
    print('SERP candidate URLs:', len(found))
    return found


def request_posts(key, urls):
    res = requests.post('https://api.brightdata.com/datasets/v3/scrape',
        params={'dataset_id': IG_DATASET, 'notify': 'false', 'include_errors': 'true'},
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={'input': [{'url': u, 'country': ''} for u in urls], 'limit_per_input': None},
        timeout=180)
    print('Instagram scrape HTTP:', res.status_code)
    res.raise_for_status()
    try:
        obj = res.json()
    except ValueError:
        obj = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    if isinstance(obj, dict):
        print('Instagram response pending or envelope:', sorted(obj)[:12])
        return []
    if not isinstance(obj, list):
        raise ValueError('Instagram response was not a list')
    return obj


def relevant(caption):
    s = str(caption or '').casefold()
    return any(x.casefold() in s for x in PERSON_TERMS) and any(x.casefold() in s for x in DIOR_TERMS)


def verify_original(url, account):
    """Fail closed if Instagram blocks verification or disagrees on author/ID."""
    ident = shortcode(url)
    if not ident or not account:
        return False
    for target in (url, url.rstrip('/') + '/embed/captioned/'):
        try:
            r = requests.get(target, timeout=12, headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            titles = [soup.title.get_text(' ', strip=True)] if soup.title else []
            for key in ('og:title', 'twitter:title'):
                meta = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
                if meta:
                    titles.append(meta.get('content', ''))
            author = re.compile(r'(?:^|\s|@)' + re.escape(account) + r'\s+(?:on Instagram|• Instagram|\(@)', re.I)
            link = soup.find('link', rel='canonical')
            ogurl = soup.find('meta', attrs={'property': 'og:url'})
            canonical = [r.url]
            if link:
                canonical.append(link.get('href', ''))
            if ogurl:
                canonical.append(ogurl.get('content', ''))
            if any(author.search(x or '') for x in titles) and any(shortcode(x) == ident for x in canonical):
                return True
        except requests.RequestException:
            continue
    return False


def main():
    key = os.environ.get('BRIGHTDATA_API_KEY')
    if not key:
        raise RuntimeError('BRIGHTDATA_API_KEY is not configured')
    state = load('media-state.json', {'search_cursor': 0, 'seen': []})
    posts = load('posts.json', {'posts': []})
    review = load('media-review-queue.json', [])
    allowed = load('trusted_media.json', {})
    trusted = {a.lower() for a in allowed.get('accounts', [])}
    excluded = {a.lower() for a in allowed.get('excluded_accounts', [])}
    seen = set(state.get('seen', []))
    seen.update(str(x.get('id') or shortcode(x.get('url')) or '') for x in posts.get('posts', []) + review)
    known_urls = {}
    cursor = int(state.get('search_cursor', 0))
    for offset in range(SEARCH_CALLS):
        query = QUERIES[(cursor + offset) % len(QUERIES)]
        try:
            urls = request_serp(key, query)
            print('SERP query index:', (cursor + offset) % len(QUERIES), 'results:', len(urls))
            for url in sorted(urls):
                ident = shortcode(url)
                if ident and ident not in seen:
                    known_urls.setdefault(ident, url)
        except requests.RequestException as exc:
            print('SERP transport failed:', type(exc).__name__)
    state['search_cursor'] = (cursor + SEARCH_CALLS) % len(QUERIES)
    picked = list(known_urls.values())[:SCRAPE_LIMIT]
    print('New unique discovered:', len(known_urls), 'selected:', len(picked))
    records = []
    if picked:
        try:
            records = request_posts(key, picked)
        except (requests.RequestException, ValueError) as exc:
            print('IG scrape failed:', type(exc).__name__)
    requested = {shortcode(u): u for u in picked}
    pending = {str(x.get('id')) for x in review}
    published = {str(x.get('id')) for x in posts.get('posts', [])}
    new_public = new_queue = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        url = record.get('url') or ''
        ident = shortcode(url)
        if not ident or ident not in requested or ident in pending or ident in published:
            print('Skipped mismatched or duplicate scraper row')
            continue
        account = str(record.get('user_posted') or '').strip().lstrip('@').lower()
        caption = str(record.get('description') or '').strip()
        item = {'id': ident, 'account': account, 'url': requested[ident],
                'date': str(record.get('date_posted') or ''), 'caption': caption[:1500],
                'review_status': 'unverified'}
        if account in trusted and account not in excluded and relevant(caption) and verify_original(item['url'], account):
            item['review_status'] = 'source_verified'
            posts.setdefault('posts', []).append(item)
            published.add(ident)
            new_public += 1
        else:
            item['review_reason'] = ('excluded_account' if account in excluded else
                 'unlisted_account' if account not in trusted else
                 'missing_topics' if not relevant(caption) else 'original_post_unverified')
            review.append(item)
            pending.add(ident)
            new_queue += 1
        seen.add(ident)
    if records:
        for ident, url in requested.items():
            if ident not in seen:
                review.append({'id': ident, 'url': url, 'account': '', 'caption': '',
                               'review_status': 'unverified', 'review_reason': 'no_matching_scraper_record'})
                seen.add(ident)
                new_queue += 1
    posts['posts'] = posts.get('posts', [])[-MAX_ROWS:]
    save('posts.json', posts)
    save('media-review-queue.json', review[-MAX_ROWS:])
    save('media-state.json', {'search_cursor': state['search_cursor'], 'seen': sorted(x for x in seen if x)[-10000:]})
    save('last-run.json', {'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
         'queries_used': SEARCH_CALLS, 'selected': len(picked), 'returned': len(records),
         'published': new_public, 'needs_review': new_queue,
         'note': 'Only independently verified posts are published. All other new records are queued.'})
    print('Finished. Media candidates queued:', new_queue, 'public additions:', new_public)

if __name__ == '__main__':
    main()
