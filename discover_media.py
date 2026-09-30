
import os
import re
import json
import urllib.parse
import requests
from bs4 import BeautifulSoup

API_KEY = os.environ["BRIGHTDATA_API_KEY"]
ZONE = "serp_api1"

SEARCHES = [
    'site:instagram.com "DiorSummer27" "Wonyoung"',
    'site:instagram.com "DiorSummer27" "Jang Wonyoung"',
    'site:instagram.com "DiorSummer27" "장원영"',
]

# 只作为媒体候选识别依据，后续可继续扩充
MEDIA_NAMES = [
    "vogue", "elle", "bazaar", "wwd", "grazia",
    "marieclaire", "cosmopolitan", "dazed",
    "dispatch", "osen", "newsen", "starnews",
    "sportsseoul", "gettyimages", "hypebeast",
]


def extract_links(page):
    import html
    import re
    import urllib.parse

    links = set()
    text = html.unescape(page)

    # 还原 JSON 转义和编码后的链接
    text = text.replace("\\/", "/")
    text = text.replace("\\u002F", "/")
    text = text.replace("\\u003A", ":")
    text = text.replace("\\u0026", "&")

    for _ in range(2):
        text = urllib.parse.unquote(text)

    pattern = (
        r"(?:https?://)?(?:www\.)?"
        r"instagram\.com/(p|reel|tv)/"
        r"([A-Za-z0-9_-]{5,})"
    )

    for match in re.finditer(pattern, text, re.I):
        kind = match.group(1).lower()
        shortcode = match.group(2)

        links.add(
            f"https://www.instagram.com/{kind}/{shortcode}/"
        )

    print("Instagram URL matches:", len(links))
    return links

all_links = set()

for query in SEARCHES:
    print("Searching:", query)

    search_url = (
        "https://www.google.com/search?q="
        + urllib.parse.quote(query)
    )

    try:
        response = requests.post(
            "https://api.brightdata.com/request",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "zone": ZONE,
                "url": search_url,
                "format": "raw",
            },
            timeout=180,
        )
        response.raise_for_status()

        print("HTTP status:", response.status_code)
        print("HTML length:", len(response.text))

        links = extract_links(response.text)
        all_links.update(links)
        print("Found:", len(links))

    except requests.RequestException as error:
        print("Search failed:", type(error).__name__)

result = {
    "post_urls": sorted(all_links),
    "count": len(all_links),
}

with open("candidates.json", "w", encoding="utf-8") as file:
    json.dump(result, file, ensure_ascii=False, indent=2)

print("Unique candidate posts:", len(all_links))
