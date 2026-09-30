
import os
import json
import requests

API_KEY = os.environ["BRIGHTDATA_API_KEY"]

DATASET_ID = "gd_lk5ns7kz21pck8jpis"

with open("candidates.json", encoding="utf-8") as f:
    candidates = json.load(f)

urls = candidates.get("post_urls", [])

if not urls:
    print("No candidates. Skipping collection.")
    raise SystemExit(0)

# 测试期间最多处理15条，避免意外消耗额度
urls = urls[:15]

inputs = [
    {"url": url, "country": ""}
    for url in urls
]

endpoint = "https://api.brightdata.com/datasets/v3/scrape"

response = requests.post(
    endpoint,
    params={
        "dataset_id": DATASET_ID,
        "notify": "false",
        "include_errors": "true",
    },
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "input": inputs,
        "limit_per_input": None,
    },
    timeout=180,
)

response.raise_for_status()

result = response.json()

with open("instagram-results.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("Submitted URLs:", len(inputs))
print("Response type:", type(result).__name__)

if isinstance(result, dict):
    print("Response fields:", list(result.keys()))

print("Instagram collection request completed.")
