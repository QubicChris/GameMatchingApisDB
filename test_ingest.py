import json
import requests

API_URL = "http://134.209.73.229:9998/"
# Load the demo snapshot
with open("pregames-snapshot-demo(1).json", "r") as f:
    payload = json.load(f)

print(f"Sending {len(payload)} game(s) to {API_URL}/ingest ...\n")

response = requests.post(f"{API_URL}/ingest", json=payload)

print(f"Status code : {response.status_code}")
print(f"Response    : {json.dumps(response.json(), indent=2)}")

# If insert worked, fetch the game back
if response.status_code == 200 and response.json()["inserted"] > 0:
    game_id = response.json()["game_ids"][0]
    print(f"\nFetching game id={game_id} ...")
    r2 = requests.get(f"{API_URL}/games/{game_id}")
    game = r2.json()
    print(f"  {game['home_team']} vs {game['away_team']}")
    print(f"  League   : {game['league']}")
    print(f"  Kickoff  : {game['date_time_starts_utc']}")
    print(f"  Company games : {len(game['company_games'])}")
    total_markets = sum(len(cg["markets"]) for cg in game["company_games"])
    print(f"  Total markets : {total_markets}")