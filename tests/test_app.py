import sqlite3

from fastapi.testclient import TestClient
from ledger_fakes import add_account, add_txn
from plaid_fakes import FakeItem, FakePlaid, account, page, txn

from fintrack import keychain
from fintrack.app import create_app
from fintrack.config import Settings
from fintrack.plaid import PlaidNotConfigured


def api_for(settings: Settings, plaid_factory) -> TestClient:
    return TestClient(create_app(settings, plaid_factory=plaid_factory, run_scheduler=False), base_url="http://127.0.0.1")


def test_linking_a_bank_keeps_its_access_token_out_of_the_database(settings: Settings, plaid: FakePlaid):
    plaid.next_exchange = ("item-chase", "access-sandbox-chase")
    plaid.items["access-sandbox-chase"] = FakeItem(
        [account("acc-card")], {None: page(added=[txn("t1", 5.75, "2026-10-02")], next_cursor="c1")}
    )
    api = api_for(settings, plaid.client)

    assert api.post("/api/link/token", json={}).json() == {"link_token": "link-sandbox-token"}
    linked = api.post(
        "/api/link/exchange",
        json={"public_token": "public-sandbox-token", "institution_id": "ins_56", "institution_name": "Chase"},
    )

    assert linked.status_code == 200
    assert keychain.get_access_token("item-chase") == "access-sandbox-chase"
    for path in settings.data_dir.glob("fintrack-sandbox.db*"):  # the database plus its WAL
        assert b"access-sandbox-chase" not in path.read_bytes()
    # Linking kicked off the history backfill in the background, and the result is already categorized.
    rows = api.get("/api/activity").json()["items"]
    assert [(r["display_name"], r["category_id"], r["flow_type"]) for r in rows] == [
        ("Blue Bottle Coffee", "dining.coffee", "expense")
    ]
    assert api.get("/api/status").json()["items"][0]["transactions_status"] == "HISTORICAL_UPDATE_COMPLETE"


def test_missing_plaid_credentials_are_reported_not_crashed_on(settings: Settings):
    def unconfigured():
        raise PlaidNotConfigured("no credentials")

    api = api_for(settings, unconfigured)

    assert api.get("/api/status").json()["plaid_configured"] is False
    assert api.post("/api/link/token", json={}).status_code == 503


def test_requests_addressed_to_other_hosts_are_refused(settings: Settings, plaid: FakePlaid):
    app = create_app(settings, plaid_factory=plaid.client, run_scheduler=False)
    assert TestClient(app, base_url="http://attacker.example").get("/api/status").status_code == 400


def test_editing_a_transaction_through_the_api(settings: Settings, plaid: FakePlaid, db: sqlite3.Connection):
    card = add_account(db, "Sapphire Preferred", "credit", institution="Chase")
    coffee = add_txn(db, card, -575, "2026-10-27", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE")
    api = api_for(settings, plaid.client)  # startup classifies existing transactions

    edited = api.patch(f"/api/transactions/{coffee}", json={"category_id": "dining.other", "note": "client lunch"})
    assert edited.status_code == 200
    assert (edited.json()["category_id"], edited.json()["note"]) == ("dining.other", "client lunch")

    note_only = api.patch(f"/api/transactions/{coffee}", json={"note": None}).json()
    assert (note_only["category_id"], note_only["note"]) == ("dining.other", None)  # category untouched

    reverted = api.patch(f"/api/transactions/{coffee}", json={"category_id": None}).json()
    assert (reverted["category_id"], reverted["category_edited"]) == ("dining.coffee", 0)

    assert api.patch(f"/api/transactions/{coffee}", json={"category_id": "dining"}).status_code == 422
    assert api.patch("/api/transactions/9999", json={"note": "x"}).status_code == 404


def test_rules_through_the_api(settings: Settings, plaid: FakePlaid, db: sqlite3.Connection):
    card = add_account(db, "Card", "credit", institution="Chase")
    add_txn(db, card, -1549, "2026-10-07", "NETFLIX.COM", merchant="Netflix", pfc="ENTERTAINMENT_TV_AND_MOVIES")
    api = api_for(settings, plaid.client)

    assert api.post("/api/rules/preview", json={"match_field": "merchant", "pattern": "netflix"}).json() == {"matches": 1}
    created = api.post("/api/rules", json={"match_field": "merchant", "pattern": "Netflix", "category_id": "bills.subscriptions"})
    assert created.status_code == 200
    rule = created.json()
    assert (rule["category_name"], rule["direction"], rule["transaction_count"]) == ("订阅会员", None, 1)
    row = api.get("/api/activity").json()["items"][0]
    assert (row["category_id"], row["category_rule"], row["user_rule_pattern"]) == ("bills.subscriptions", "user_rule", "Netflix")

    changed = api.patch(f"/api/rules/{rule['id']}", json={"category_id": "entertainment"}).json()
    assert changed["category_id"] == "entertainment"
    assert api.post("/api/rules", json={"match_field": "merchant", "pattern": " ", "category_id": "entertainment"}).status_code == 422
    assert api.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert api.get("/api/rules").json() == []
    assert api.delete(f"/api/rules/{rule['id']}").status_code == 404


def test_insights_endpoints(settings: Settings, plaid: FakePlaid):
    api = api_for(settings, plaid.client)

    trend = api.get("/api/insights/trend", params={"granularity": "week"}).json()
    assert trend["granularity"] == "week" and len(trend["periods"]) == 26
    breakdown = api.get("/api/insights/breakdown", params={"granularity": "month", "compare": "average"}).json()
    assert len(breakdown["comparison_periods"]) == 3
    assert api.get("/api/insights/breakdown", params={"compare": "sideways"}).status_code == 422


def test_overview_and_categories_endpoints(settings: Settings, plaid: FakePlaid):
    api = api_for(settings, plaid.client)

    overview = api.get("/api/overview").json()
    assert set(overview) == {"today", "period", "previous_period", "income", "spending", "net_cash"}
    categories = {c["id"]: c for c in api.get("/api/categories").json()}
    assert categories["dining"]["assignable"] == 0 and categories["dining.coffee"]["assignable"] == 1


def test_the_react_app_is_served_for_client_side_routes(settings: Settings, plaid: FakePlaid):
    api = api_for(settings, plaid.client)
    assert api.get("/").status_code == 503  # not built yet: the page explains how to build it

    (settings.web_dist / "assets").mkdir(parents=True)
    (settings.web_dist / "index.html").write_text("<div id=root></div>")
    (settings.web_dist / "assets" / "app.js").write_text("console.log(1)")
    (settings.data_dir / "secret.txt").write_text("not for the browser")

    assert api.get("/activity").text == "<div id=root></div>"
    assert api.get("/assets/app.js").text == "console.log(1)"
    assert api.get("/..%2Fsecret.txt").text == "<div id=root></div>"  # never escapes the build directory
    assert api.get("/api/nope").status_code == 404


def test_card_payments_endpoint(settings: Settings, plaid: FakePlaid):
    assert api_for(settings, plaid.client).get("/api/card-payments").json() == []
