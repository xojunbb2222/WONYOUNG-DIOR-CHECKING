
import os
import json
import requests

API_KEY = os.environ["BRIGHTDATA_API_KEY"]
DATASET_ID = "gd_lk5ns7kz21pck8jpis"

with open("candidates.json", encoding="utf-8") as f:
    candidates = json.load(f)

urls = candidates.get("post_urls", [])

if not urls:
    print("No candidates found.")
    with open("instagram-results.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    raise SystemExit(0)

# 测试阶段最多抓取15条
urls = urls[:15]

inputs = [
    {"url": url, "country": ""}
    for url in urls
]

print("Submitting Instagram URLs:", len(inputs))

response = requests.post(
    "https://api.brightdata.com/datasets/v3/scrape",
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

print("HTTP status:", response.status_code)
print("Response size:", len(response.content))
print("Content-Type:", response.headers.get("Content-Type", ""))

# 首先保存原始响应，避免解析失败后丢失数据
with open("instagram-response.txt", "w", encoding="utf-8") as f:
    f.write(response.text)

response.raise_for_status()

# 兼容标准 JSON 和逐行 JSON（NDJSON）
try:
    result = response.json()
    print("Format: Standard JSON")

except ValueError:
    try:
        result = [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]
        print("Format: NDJSON")

    except ValueError:
        print("Unable to parse response.")
        print("Raw response saved.")
        raise SystemExit(1)

# 如果返回的是 snapshot ID，则说明还需要下载任务结果
if isinstance(result, dict) and "snapshot_id" in result:
    print("Snapshot ID:", result["snapshot_id"])
    print("Snapshot retrieval will be needed.")

with open("instagram-results.json", "w", encoding="utf-8") as f:
    json.dump(
        result,
        f,
        ensure_ascii=False,
        indent=2
    )

if isinstance(result, list):
    print("Records returned:", len(result))
elif isinstance(result, dict):
    print("Response fields:", list(result.keys()))

print("Instagram collection response saved.")
