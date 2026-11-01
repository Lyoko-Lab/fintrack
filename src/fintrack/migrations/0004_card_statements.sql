-- Credit card statements and payment due dates, from Plaid Liabilities (docs/DESIGN.md §3).
--
-- One row per card: the latest statement and the payment due on it, replaced whenever a
-- sync gets fresh data. Amounts are cents owed (positive), as the bank reports them.

CREATE TABLE card_statements (
    account_id          INTEGER PRIMARY KEY REFERENCES accounts (id),
    statement_date      TEXT,     -- when the last statement was issued
    statement_cents     INTEGER,  -- the total owed on that statement
    minimum_cents       INTEGER,  -- the minimum payment due
    due_date            TEXT,     -- when the next payment is due; NULL when none is expected
    last_payment_cents  INTEGER,
    last_payment_date   TEXT,
    is_overdue          INTEGER,  -- 1 or 0; NULL when the bank doesn't say
    updated_at          TEXT NOT NULL
);
