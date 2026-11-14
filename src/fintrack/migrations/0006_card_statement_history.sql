-- Card statements become a history (docs/DESIGN.md §4): a row for each distinct report the bank
-- gives about a card, rather than one row per card overwritten on every sync. A sync that gets
-- the same report again only moves its updated_at; a new statement, a payment the bank has seen,
-- or a changed due date starts a new row. v_card_statements (views.sql) is the latest per card.

CREATE TABLE card_statement_history (
    id                  INTEGER PRIMARY KEY,
    account_id          INTEGER NOT NULL REFERENCES accounts (id),
    statement_date      TEXT,     -- when the statement was issued
    statement_cents     INTEGER,  -- the total owed on it
    minimum_cents       INTEGER,  -- the minimum payment due
    due_date            TEXT,     -- when the next payment is due; NULL when none is expected
    last_payment_cents  INTEGER,
    last_payment_date   TEXT,
    is_overdue          INTEGER,  -- 1 or 0; NULL when the bank doesn't say
    first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),  -- the sync that first got it
    updated_at          TEXT NOT NULL     -- the latest sync that still got it
);

INSERT INTO card_statement_history (account_id, statement_date, statement_cents, minimum_cents, due_date,
                                    last_payment_cents, last_payment_date, is_overdue, first_seen_at, updated_at)
SELECT account_id, statement_date, statement_cents, minimum_cents, due_date,
       last_payment_cents, last_payment_date, is_overdue, updated_at, updated_at
FROM card_statements;

DROP TABLE card_statements;
ALTER TABLE card_statement_history RENAME TO card_statements;
CREATE INDEX card_statements_by_account ON card_statements (account_id, id);
