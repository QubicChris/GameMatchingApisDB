
import json
import requests
from pathlib import Path

#INGEST_URL = "http://134.209.73.229:9998/ingest"
INGEST_URL = "http://77.237.244.129:9998/ingest"
#INGEST_URL = "http://localhost:9998/ingest"
PAYLOADS_DIR = Path("payloads22")

payloads = sorted(PAYLOADS_DIR.glob("payload_*.json"))

for payload_file in payloads:
    print(f"Sending {payload_file.name}...")
    with open(payload_file) as f:
        data = json.load(f)
    response = requests.post(INGEST_URL, json=data)
    print(f"  Status: {response.status_code}")
    try:
        print(f"  Response: {response.json()}\n")
    except Exception:
        print(f"  Response (raw): {response.text}\n")
