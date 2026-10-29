"""Fill a separate database with two years of made-up transactions, for building and checking the UI.

Real data never enters a development session (CLAUDE.md), so screens are checked against
this instead. It only ever writes .dev-data/fintrack-sandbox.db:

    uv run python scripts/seed_demo.py
    FINTRACK_ENV=sandbox FINTRACK_DATA_DIR=.dev-data FINTRACK_PORT=8788 uv run fintrack serve

(.claude/launch.json has the second command as `fintrack-demo`.) The banks, people and
merchants are invented or generic; the items use provider "demo", so nothing tries to sync them.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fintrack.config import REPO_ROOT, Settings
from fintrack.db import open_db, transaction, utcnow
from fintrack.enrich import enrich_all

DEMO_DIR = REPO_ROOT / ".dev-data"
DAYS = 730
OPENING_CHECKING_BALANCE = 800_000

# institution → [(key, account name, mask, type, subtype)]
INSTITUTIONS = {
    "Northwind Bank": [
        ("checking", "Everyday Checking", "0101", "depository", "checking"),
        ("rewards", "Rewards Card", "0202", "credit", "credit card"),
    ],
    "Contoso Card": [
        ("dining", "Dining Card", "0303", "credit", "credit card"),
        ("travel", "Travel Card", "0404", "credit", "credit card"),
        ("grocery", "Grocery Card", "0505", "credit", "credit card"),
    ],
    "Fabrikam Express": [
        ("online", "Online Card", "0606", "credit", "credit card"),
        ("spare", "Spare Card", "0707", "credit", "credit card"),
    ],
}
# How each bank's checking account describes paying that bank's cards.
CARD_PAYMENT = {
    "Northwind Bank": "NORTHWIND CREDIT CRD DES:AUTOPAY ID:000000",
    "Contoso Card": "CONTOSO CARD SERVICES DES:EPAY ID:000000",
    "Fabrikam Express": "FABRIKAM EXPRESS DES:ACH PMT ID:000000",
}


def generate(today: date, rng: random.Random) -> list[tuple[str, int, date, str, str | None, str | None]]:
    """(account key, cents, date, bank description, merchant, Plaid category) for every made-up transaction."""
    rows: list[tuple[str, int, date, str, str | None, str | None]] = []

    def add(key: str, cents: int, day: date, text: str, merchant: str | None = None, pfc: str | None = None) -> None:
        rows.append((key, cents, day, text, merchant, pfc))

    def pick(options: list[tuple[str, str, str]]) -> tuple[str, str, str]:
        return options[rng.randrange(len(options))]

    start = today - timedelta(days=DAYS)
    trips = {date(year, month, day) for year in range(start.year, today.year + 1) for month, day in ((3, 12), (6, 21), (9, 6), (12, 20))}
    day = start
    while day <= today:
        weekend = day.weekday() >= 5
        if day.weekday() == 4 and (day - date(2024, 1, 5)).days % 14 == 0:
            add("checking", 385_000, day, "NORTHWIND LABS DES:PAYROLL ID:000000 INDN:ALEX SAMPLE PPD", None, "INCOME_WAGES")
        if day.day == 1:
            add("checking", -260_000, day, "OAK STREET APTS DES:RENT ID:000000", "Oak Street Apartments", "RENT_AND_UTILITIES_RENT")
            add("rewards", -7_499, day, "COMCAST CABLE COMM", "Comcast", "RENT_AND_UTILITIES_INTERNET_AND_CABLE")
            add("rewards", -1_549, day, "NETFLIX.COM", "Netflix", "ENTERTAINMENT_TV_AND_MOVIES")
        if day.day == 3:
            add("rewards", -21_500, day, "BAYSIDE FITNESS CLUB", "Bayside Fitness", "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS")
        if day.day == 12:
            winter = day.month in (11, 12, 1, 2)
            add("rewards", -rng.randint(11_000, 19_000) if winter else -rng.randint(6_000, 11_000), day,
                "CITY POWER & GAS", "City Power & Gas", "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY")  # fmt: skip
        if day.day == 18:
            add("rewards", -5_500, day, "MOBILE CARRIER AUTOPAY", "Mobile Carrier", "RENT_AND_UTILITIES_TELEPHONE")
        if day.day == 28:
            add("online", -1_199, day, "SPOTIFY USA", "Spotify", "ENTERTAINMENT_MUSIC_AND_AUDIO")
        if (day + timedelta(days=1)).day == 1:
            add("checking", rng.randint(150, 650), day, "INTEREST EARNED", None, "INCOME_INTEREST_EARNED")
        if day.month == 4 and day.day == 15:
            add("checking", rng.randint(80_000, 200_000), day, "IRS TREAS 310 TAX REF", None, "INCOME_TAX_REFUND")

        if not weekend and rng.random() < 0.6:
            name, merchant, pfc = pick([("BLUE BOTTLE COFFEE", "Blue Bottle Coffee", "FOOD_AND_DRINK_COFFEE"),
                                        ("STARBUCKS STORE 01234", "Starbucks", "FOOD_AND_DRINK_COFFEE")])  # fmt: skip
            add("dining", -rng.randint(450, 850), day, name, merchant, pfc)
        if rng.random() < (0.5 if weekend else 0.3):
            name, merchant, pfc = pick([("SWEETGREEN 123", "Sweetgreen", "FOOD_AND_DRINK_RESTAURANT"),
                                        ("HARBOR NOODLE HOUSE", "Harbor Noodle House", "FOOD_AND_DRINK_RESTAURANT"),
                                        ("CHIPOTLE 2210", "Chipotle", "FOOD_AND_DRINK_FAST_FOOD"),
                                        ("GREEN TABLE BISTRO", "Green Table Bistro", "FOOD_AND_DRINK_RESTAURANT")])  # fmt: skip
            add("dining", -rng.randint(1_400, 9_500), day, name, merchant, pfc)
        if weekend and rng.random() < 0.7:
            name, merchant, pfc = pick([("WHOLE FOODS MARKET", "Whole Foods Market", "FOOD_AND_DRINK_GROCERIES"),
                                        ("TRADER JOE S #123", "Trader Joe's", "FOOD_AND_DRINK_GROCERIES"),
                                        ("SAFEWAY #0456", "Safeway", "FOOD_AND_DRINK_GROCERIES")])  # fmt: skip
            add("grocery", -rng.randint(4_500, 18_000), day, name, merchant, pfc)
        if rng.random() < 0.25:
            name, merchant, pfc = pick([("UBER *TRIP", "Uber", "TRANSPORTATION_TAXIS_AND_RIDE_SHARES"),
                                        ("LYFT *RIDE", "Lyft", "TRANSPORTATION_TAXIS_AND_RIDE_SHARES")])  # fmt: skip
            add("travel", -rng.randint(900, 4_500), day, name, merchant, pfc)
        if rng.random() < (0.5 if day.month == 12 else 0.2):
            name, merchant, pfc = pick([("AMAZON MKTPL*AB12CD", "Amazon", "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES"),
                                        ("TARGET 00012345", "Target", "GENERAL_MERCHANDISE_SUPERSTORES"),
                                        ("UNIQLO USA", "Uniqlo", "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES")])  # fmt: skip
            add("online", -rng.randint(1_200, 30_000 if day.month == 12 else 15_000), day, name, merchant, pfc)
        if rng.random() < 0.02:
            add("online", rng.randint(1_500, 6_000), day, "AMAZON MKTPL REFUND", "Amazon", "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES")
        if rng.random() < 0.06:
            add("travel", -rng.randint(3_500, 7_000), day, "SHELL OIL 57444", "Shell", "TRANSPORTATION_GAS")
        if rng.random() < 0.01:
            add("rewards", -rng.randint(2_500, 25_000), day, "BAYVIEW MEDICAL GROUP", "Bayview Medical", "MEDICAL_PRIMARY_CARE")
        if rng.random() < 0.04:
            add("checking", -rng.randint(1_500, 6_000), day, "VENMO PAYMENT 1023456789")
        if rng.random() < 0.03:
            add("checking", rng.randint(2_000, 8_000), day, "Zelle payment from SAM SAMPLE Conf# demo")
        if rng.random() < 0.01:
            add("spare", -rng.randint(800, 4_000), day, "CORNER BOOKSHOP", "Corner Bookshop", "GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS")
        if day in trips:
            add("travel", -rng.randint(28_000, 72_000), day - timedelta(days=21), "UNITED AIRLINES 0162", "United Airlines", "TRAVEL_FLIGHTS")
            add("travel", -rng.randint(45_000, 140_000), day + timedelta(days=4), "HARBORVIEW HOTEL", "Harborview Hotel", "TRAVEL_LODGING")
        day += timedelta(days=1)

    # Every card is paid in full on the 22nd for the month before, from checking.
    owed: dict[tuple[str, int, int], int] = defaultdict(int)
    for key, cents, day, *_ in rows:
        if key != "checking":
            owed[(key, day.year, day.month)] -= cents
    institution_of = {key: name for name, accounts in INSTITUTIONS.items() for key, *_ in accounts}
    for (key, year, month), amount in owed.items():
        due = date(year + month // 12, month % 12 + 1, 22)
        if amount > 0 and due <= today:
            add("checking", -amount, due, CARD_PAYMENT[institution_of[key]])
            add(key, amount, due + timedelta(days=1), "AUTOMATIC PAYMENT - THANK YOU")
    return [row for row in rows if start <= row[2] <= today]


def main() -> int:
    path = Settings(env="sandbox", data_dir=DEMO_DIR).db_path
    if path.exists():
        conn = open_db(path)
        foreign = conn.execute("SELECT COUNT(*) FROM items WHERE provider != 'demo'").fetchone()[0]
        conn.close()
        if foreign:
            print(f"{path} holds items that are not demo data; leaving it alone.", file=sys.stderr)
            return 1
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)

    today = date.today()
    rows = generate(today, random.Random(2026))
    conn = open_db(path)
    now = utcnow()
    with transaction(conn):
        ids: dict[str, int] = {}
        for institution, accounts in INSTITUTIONS.items():
            item_id = conn.execute(
                """
                INSERT INTO items (provider, external_id, institution_name, transactions_status, last_synced_at, created_at)
                VALUES ('demo', ?, ?, 'HISTORICAL_UPDATE_COMPLETE', ?, ?) RETURNING id
                """,
                (f"demo-{institution}", institution, now, now),
            ).fetchone()[0]
            for key, name, mask, type_, subtype in accounts:
                ids[key] = conn.execute(
                    """
                    INSERT INTO accounts (item_id, external_id, name, mask, type, subtype, currency, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'USD', ?) RETURNING id
                    """,
                    (item_id, f"demo-{key}", name, mask, type_, subtype, now),
                ).fetchone()[0]
        conn.executemany(
            """
            INSERT INTO transactions (account_id, external_id, pending, amount_cents, currency, transaction_date,
                                      posted_date, merchant_name, description, original_description, pfc_detailed,
                                      first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (ids[key], f"demo-{n}", int((today - day).days < 2), cents, day.isoformat(), day.isoformat(),
                 merchant, merchant or text, text, pfc, now, now)  # fmt: skip
                for n, (key, cents, day, text, merchant, pfc) in enumerate(rows)
            ],
        )
        # Balances: checking from an opening balance; a card owes whatever hasn't been paid yet.
        balances: dict[str, int] = defaultdict(int)
        for key, cents, *_ in rows:
            balances[key] += cents
        for key, account_id in ids.items():
            current = OPENING_CHECKING_BALANCE + balances[key] if key == "checking" else -balances[key]
            conn.execute(
                "UPDATE accounts SET current_cents = ?, balance_as_of = ? WHERE id = ?", (current, today.isoformat(), account_id)
            )
    enrich_all(conn)
    print(f"Wrote {len(rows)} made-up transactions to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
