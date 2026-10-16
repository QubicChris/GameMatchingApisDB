from webapi.queries import pivot_odds


def r(company, outcome, odd, line=None, umid=1, name="Match Result", close=None, win=None):
    return {"umid": umid, "market_name": name, "outcome": outcome, "line_value": line,
            "company_name": company, "odd": odd, "sofa_close": close, "sofa_winning": win}


def test_two_bookmakers_three_outcomes():
    rows = [r(b, o, 2.0) for o in ("home", "draw", "away") for b in ("A", "B")]
    out = pivot_odds(rows)
    assert out["bookmakers"] == ["A", "B"]
    assert len(out["markets"]) == 1
    mrows = out["markets"][0]["rows"]
    assert len(mrows) == 3
    assert all(set(x["odds"]) == {"A", "B"} for x in mrows)


def test_missing_selection_is_none():
    out = pivot_odds([r("A", "home", 2.0), r("B", "home", 2.1), r("A", "draw", 3.0)])
    draw = out["markets"][0]["rows"][1]
    assert draw["odds"] == {"A": 3.0, "B": None}


def test_labels():
    out = pivot_odds([r("A", "over", 1.9, line=2.5, umid=50), r("A", "home", 1.9, line=-1.0, umid=51)])
    assert out["markets"][0]["rows"][0]["label"] == "over 2.5"
    assert out["markets"][1]["rows"][0]["label"] == "home -1"


def test_market_name_fallback():
    out = pivot_odds([r("A", "home", 2.0, umid=77, name=None)])
    assert out["markets"][0]["name"] == "Market 77"


def test_order_follows_input():
    out = pivot_odds([r("A", "x", 1, umid=9), r("A", "b", 1, umid=2), r("A", "a", 1, umid=2)])
    assert [m["umid"] for m in out["markets"]] == [9, 2]
    assert [x["outcome"] for x in out["markets"][1]["rows"]] == ["b", "a"]


def test_sofa_close_from_any_company():
    out = pivot_odds([r("A", "home", 2.0), r("B", "home", 2.1, close=1.95, win=1)])
    row = out["markets"][0]["rows"][0]
    assert row["sofa_close"] == 1.95 and row["sofa_winning"] == 1
