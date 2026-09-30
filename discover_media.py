
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
    soup = BeautifulSoup(page, "html.parser")
    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/url?"):
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(href).query
            )
            href = query.get("q", [""])[0]

        match = re.search(
            r"https?://(?:www\.)?instagram\.com/"
            r"(?:p|reel)/[A-Za-z0-9_-]+",
            href,
        )
        if match:
            links.add(match.group(0).split("?")[0] + "/")

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
