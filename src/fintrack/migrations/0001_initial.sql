-- Initial schema: the Raw and Ledger layers (docs/DESIGN.md §4).
--
-- Conventions
--   * Money is integer cents.
--   * Transaction amounts are signed from the owner's point of view:
--     money in > 0, money out < 0. Plaid reports the opposite sign.
--   * Timestamps are UTC ISO-8601 text ("2026-10-28T13:05:00Z"); dates are "YYYY-MM-DD".
--   * Nothing is hard-deleted: a transaction the provider retracts gets removed_at.

-- One row per bank login ("Item" in Plaid). Its access token lives in the Keychain, not here.
CREATE TABLE items (
    id                  INTEGER PRIMARY KEY,
    provider            TEXT NOT NULL DEFAULT 'plaid',
    external_id         TEXT NOT NULL,
    institution_id      TEXT,
    institution_name    TEXT,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'login_required', 'error')),
    sync_cursor         TEXT,               -- /transactions/sync cursor; NULL until data is first available
    transactions_status TEXT,               -- Plaid transactions_update_status from the last sync
    last_synced_at      TEXT,
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (provider, external_id)
);

CREATE TABLE accounts (
    id               INTEGER PRIMARY KEY,
    item_id          INTEGER NOT NULL REFERENCES items (id),
    external_id      TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    official_name    TEXT,
    mask             TEXT,                  -- last 4 digits
    type             TEXT NOT NULL,         -- depository | credit | loan | investment | other
    subtype          TEXT,                  -- checking | savings | credit card | ...
    currency         TEXT,
    current_cents    INTEGER,               -- latest reported balance; for credit cards, the amount owed
    available_cents  INTEGER,
    limit_cents      INTEGER,
    balance_as_of    TEXT,
    created_at       TEXT NOT NULL
);

-- One row per account per local calendar day; a later sync on the same day overwrites it.
CREATE TABLE balance_snapshots (
    account_id       INTEGER NOT NULL REFERENCES accounts (id),
    as_of            TEXT NOT NULL,
    current_cents    INTEGER,
    available_cents  INTEGER,
    limit_cents      INTEGER,
    captured_at      TEXT NOT NULL,
    PRIMARY KEY (account_id, as_of)
);

CREATE TABLE transactions (
    id                   INTEGER PRIMARY KEY,
    account_id           INTEGER NOT NULL REFERENCES accounts (id),
    external_id          TEXT NOT NULL UNIQUE,
    pending              INTEGER NOT NULL CHECK (pending IN (0, 1)),
    pending_external_id  TEXT,              -- on a posted transaction: the pending one it replaced
    amount_cents         INTEGER NOT NULL,  -- money in > 0, money out < 0
    currency             TEXT,
    transaction_date     TEXT NOT NULL,     -- when it happened: authorized_date, else posted_date; all reports use this
    authorized_date      TEXT,
    posted_date          TEXT NOT NULL,     -- Plaid `date`: posting date (occurrence date while pending)
    merchant_name        TEXT,
    description          TEXT,              -- Plaid `name`
    original_description TEXT,              -- statement text exactly as the bank shows it
    merchant_entity_id   TEXT,
    payment_channel      TEXT,              -- online | in store | other
    pfc_primary          TEXT,              -- Plaid personal_finance_category
    pfc_detailed         TEXT,
    pfc_confidence       TEXT,
    logo_url             TEXT,
    website              TEXT,
    removed_at           TEXT,
    first_seen_at        TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX transactions_by_date ON transactions (transaction_date);
CREATE INDEX transactions_by_account ON transactions (account_id, transaction_date);

CREATE TABLE sync_runs (
    id            INTEGER PRIMARY KEY,
    triggered_by  TEXT NOT NULL,            -- manual | link | cli | schedule
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'success', 'partial', 'failed')),
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    summary       TEXT                      -- JSON: per-item counts and errors
);

-- Raw layer: every provider response body exactly as received. Append-only.
CREATE TABLE raw_events (
    id           INTEGER PRIMARY KEY,
    sync_run_id  INTEGER NOT NULL REFERENCES sync_runs (id),
    item_id      INTEGER NOT NULL REFERENCES items (id),
    endpoint     TEXT NOT NULL,
    payload      TEXT NOT NULL,
    received_at  TEXT NOT NULL
);

CREATE INDEX raw_events_by_item ON raw_events (item_id, received_at);

CREATE VIEW v_transactions AS
SELECT
    t.id,
    t.transaction_date,
    t.posted_date,
    t.pending,
    t.amount_cents,
    t.currency,
    COALESCE(t.merchant_name, t.description, t.original_description) AS display_name,
    t.merchant_name,
    t.description,
    t.original_description,
    t.pfc_primary,
    t.pfc_detailed,
    t.account_id,
    a.name AS account_name,
    a.mask AS account_mask,
    a.type AS account_type,
    i.institution_name
FROM transactions t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
WHERE t.removed_at IS NULL;
