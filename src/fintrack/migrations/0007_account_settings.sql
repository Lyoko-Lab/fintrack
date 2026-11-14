-- The user's own settings for an account (docs/DESIGN.md §4). Like transaction_overrides, sync
-- never writes here: accounts holds what the bank says, this table what the user decided.
-- v_accounts (views.sql) applies them.

CREATE TABLE account_settings (
    account_id  INTEGER PRIMARY KEY REFERENCES accounts (id),
    nickname    TEXT CHECK (nickname IS NULL OR trim(nickname) <> ''),  -- shown instead of the bank's name
    excluded    INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),   -- 1: left out of totals and the forecast
    updated_at  TEXT NOT NULL
);
