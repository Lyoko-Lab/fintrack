-- Enrichment layer (docs/DESIGN.md §4): category taxonomy, derived classification, user edits.
--
-- A category's kind decides how its transactions count: expense and income feed the
-- totals (a positive amount in an expense category is a refund and reduces spending),
-- transfer is shown in Activity but kept out of income and spending.

CREATE TABLE categories (
    id         TEXT PRIMARY KEY,               -- stable slug, e.g. 'dining.coffee'
    parent_id  TEXT REFERENCES categories (id),
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('expense', 'income', 'transfer')),
    position   INTEGER NOT NULL
);

INSERT INTO categories (id, parent_id, name, kind, position) VALUES
    ('dining',               NULL,        '餐饮',           'expense',  100),
    ('dining.restaurants',   'dining',    '餐厅',           'expense',  101),
    ('dining.fast_food',     'dining',    '快餐',           'expense',  102),
    ('dining.coffee',        'dining',    '咖啡茶饮',       'expense',  103),
    ('dining.bars',          'dining',    '酒水',           'expense',  104),
    ('dining.other',         'dining',    '其他餐饮',       'expense',  105),
    ('groceries',            NULL,        '超市买菜',       'expense',  200),
    ('shopping',             NULL,        '购物',           'expense',  300),
    ('shopping.online',      'shopping',  '网购',           'expense',  301),
    ('shopping.general',     'shopping',  '商超百货',       'expense',  302),
    ('shopping.clothing',    'shopping',  '服饰',           'expense',  303),
    ('shopping.electronics', 'shopping',  '数码电子',       'expense',  304),
    ('shopping.other',       'shopping',  '其他购物',       'expense',  305),
    ('transport',            NULL,        '交通',           'expense',  400),
    ('transport.rideshare',  'transport', '打车',           'expense',  401),
    ('transport.gas',        'transport', '加油',           'expense',  402),
    ('transport.parking',    'transport', '停车过路费',     'expense',  403),
    ('transport.transit',    'transport', '公共交通',       'expense',  404),
    ('transport.auto',       'transport', '汽车相关',       'expense',  405),
    ('travel',               NULL,        '旅行',           'expense',  500),
    ('travel.flights',       'travel',    '机票',           'expense',  501),
    ('travel.lodging',       'travel',    '住宿',           'expense',  502),
    ('travel.other',         'travel',    '其他旅行',       'expense',  503),
    ('housing',              NULL,        '住房',           'expense',  600),
    ('housing.rent',         'housing',   '房租',           'expense',  601),
    ('housing.mortgage',     'housing',   '房贷',           'expense',  602),
    ('housing.home',         'housing',   '家居维修',       'expense',  603),
    ('bills',                NULL,        '账单',           'expense',  700),
    ('bills.utilities',      'bills',     '水电燃气',       'expense',  701),
    ('bills.telecom',        'bills',     '网络话费',       'expense',  702),
    ('bills.insurance',      'bills',     '保险',           'expense',  703),
    ('bills.subscriptions',  'bills',     '订阅会员',       'expense',  704),
    ('entertainment',        NULL,        '娱乐',           'expense',  800),
    ('health',               NULL,        '健康',           'expense',  900),
    ('health.medical',       'health',    '医疗',           'expense',  901),
    ('health.fitness',       'health',    '健身',           'expense',  902),
    ('personal',             NULL,        '个人与生活',     'expense', 1000),
    ('personal.care',        'personal',  '个人护理',       'expense', 1001),
    ('personal.education',   'personal',  '教育',           'expense', 1002),
    ('personal.services',    'personal',  '生活服务',       'expense', 1003),
    ('gifts',                NULL,        '礼物与捐赠',     'expense', 1100),
    ('taxes',                NULL,        '税费',           'expense', 1200),
    ('fees',                 NULL,        '利息与手续费',   'expense', 1300),
    ('fees.interest',        'fees',      '利息',           'expense', 1301),
    ('fees.bank',            'fees',      '银行手续费',     'expense', 1302),
    ('other',                NULL,        '其他支出',       'expense', 1400),
    ('other.p2p',            'other',     '个人转账',       'expense', 1401),
    ('other.reimbursement',  'other',     'AA 与报销收回',  'expense', 1402),
    ('other.credits',        'other',     '返现与账单抵扣', 'expense', 1403),
    ('other.cash',           'other',     '取现',           'expense', 1404),
    ('other.uncategorized',  'other',     '未分类',         'expense', 1405),
    ('income',               NULL,        '收入',           'income',  2000),
    ('income.salary',        'income',    '工资',           'income',  2001),
    ('income.interest',      'income',    '利息收入',       'income',  2002),
    ('income.tax_refund',    'income',    '退税',           'income',  2003),
    ('income.other',         'income',    '其他收入',       'income',  2004),
    ('transfer',             NULL,        '转账',           'transfer', 3000),
    ('transfer.card_payment','transfer',  '信用卡还款',     'transfer', 3001),
    ('transfer.internal',    'transfer',  '账户间转账',     'transfer', 3002),
    ('transfer.loan',        'transfer',  '借贷往来',       'transfer', 3003),
    ('transfer.other',       'transfer',  '其他转账',       'transfer', 3004);

-- Derived by enrich.py after every sync and rewritten from scratch each time.
CREATE TABLE transaction_enrichment (
    transaction_id    INTEGER PRIMARY KEY REFERENCES transactions (id),
    category_id       TEXT NOT NULL REFERENCES categories (id),
    rule              TEXT NOT NULL,           -- which rule decided: account | p2p | card_payment | payroll | ... | pfc | pair
    transfer_peer_id  INTEGER REFERENCES transactions (id)  -- the other half of a matched transfer
);

-- The user's own edits. Sync never writes here; enrichment only carries a pending
-- transaction's edits over to the posted transaction that replaces it.
CREATE TABLE transaction_overrides (
    transaction_id  INTEGER PRIMARY KEY REFERENCES transactions (id),
    category_id     TEXT REFERENCES categories (id),
    note            TEXT,
    updated_at      TEXT NOT NULL
);

DROP VIEW v_transactions;

-- The ledger as every reader sees it (Overview, Activity, and later Ask): live
-- transactions with the user's edits applied over the derived classification.
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
    t.original_description,
    t.logo_url,
    t.pfc_detailed,
    a.id AS account_id,
    a.name AS account_name,
    a.mask AS account_mask,
    a.type AS account_type,
    i.institution_name,
    c.id AS category_id,
    c.name AS category_name,
    COALESCE(p.name, c.name) AS category_group,
    c.kind AS flow_type,
    o.category_id IS NOT NULL AS category_edited,
    e.rule AS category_rule,
    e.transfer_peer_id,
    pa.name AS peer_account_name,
    pa.mask AS peer_account_mask,
    o.note
FROM transactions t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
LEFT JOIN transaction_enrichment e ON e.transaction_id = t.id
LEFT JOIN transaction_overrides o ON o.transaction_id = t.id
LEFT JOIN categories c ON c.id = COALESCE(o.category_id, e.category_id)
LEFT JOIN categories p ON p.id = c.parent_id
LEFT JOIN transactions pt ON pt.id = e.transfer_peer_id
LEFT JOIN accounts pa ON pa.id = pt.account_id
WHERE t.removed_at IS NULL;
