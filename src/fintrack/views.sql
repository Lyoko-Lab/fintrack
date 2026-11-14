-- The views: queries over the tables, not data. They're code, so they live here rather than in
-- migrations, and are dropped and created again every time the database is opened (db.migrate).
-- To change one, edit it here; migrations are for tables and the data in them.

DROP VIEW IF EXISTS v_ledger;
DROP VIEW IF EXISTS v_accounts;
DROP VIEW IF EXISTS v_card_statements;

-- The accounts as the user sees them: the bank's details with the user's settings applied. A
-- nickname replaces the bank's name everywhere; an excluded account is left out of every total.
CREATE VIEW v_accounts AS
SELECT
    a.id,
    a.item_id,
    COALESCE(s.nickname, a.name) AS name,
    a.name AS bank_name,
    s.nickname,
    a.official_name,
    a.mask,
    a.type,
    a.subtype,
    a.currency,
    a.current_cents,
    a.available_cents,
    a.limit_cents,
    a.balance_as_of,
    COALESCE(s.excluded, 0) AS excluded,
    i.institution_name
FROM accounts a
JOIN items i ON i.id = a.item_id
LEFT JOIN account_settings s ON s.account_id = a.id;

-- The ledger as every reader sees it (Overview, Activity, Insights, the forecast, and later Ask):
-- live transactions, with the user's edits applied over the derived classification.
CREATE VIEW v_ledger AS
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
    t.logo_url,
    t.pfc_detailed,
    a.id AS account_id,
    a.name AS account_name,
    a.mask AS account_mask,
    a.type AS account_type,
    a.excluded AS account_excluded,
    a.institution_name,
    c.id AS category_id,
    c.name AS category_name,
    COALESCE(p.name, c.name) AS category_group,
    c.kind AS flow_type,
    o.category_id IS NOT NULL AS category_edited,
    e.rule AS category_rule,
    e.user_rule_id,
    r.match_field AS user_rule_field,
    r.pattern AS user_rule_pattern,
    e.transfer_peer_id,
    pa.name AS peer_account_name,
    pa.mask AS peer_account_mask,
    o.note
FROM transactions t
JOIN v_accounts a ON a.id = t.account_id
LEFT JOIN transaction_enrichment e ON e.transaction_id = t.id
LEFT JOIN category_rules r ON r.id = e.user_rule_id
LEFT JOIN transaction_overrides o ON o.transaction_id = t.id
LEFT JOIN categories c ON c.id = COALESCE(o.category_id, e.category_id)
LEFT JOIN categories p ON p.id = c.parent_id
LEFT JOIN transactions pt ON pt.id = e.transfer_peer_id
LEFT JOIN v_accounts pa ON pa.id = pt.account_id
WHERE t.removed_at IS NULL;

-- Each card's latest statement report; card_statements keeps every one the bank has given.
CREATE VIEW v_card_statements AS
SELECT s.*
FROM card_statements s
WHERE s.id = (SELECT MAX(latest.id) FROM card_statements latest WHERE latest.account_id = s.account_id);
