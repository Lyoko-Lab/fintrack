# Fintrack design

English | [简体中文](DESIGN.zh-CN.md)

A personal finance system: every day it syncs all transactions from BOA, Chase and Amex into one ledger, with income and spending analysis and Q&A powered by Claude. It runs locally, with a web interface.

**Decisions confirmed (2026-10-28)**: Plaid Trial as the data source; a Python backend and a React frontend; 2 years of history; money friends pay back for a shared expense offsets spending in its category instead of counting as income. Investment accounts are left out for now.

## 1. Features

| Feature | What it does |
|---|---|
| **Overview** | Home page: three headline tiles, Income MTD, Spending MTD and Net Cash Position (each compared with the same point last month), then the cash flow forecast, the credit card payment calendar and recent transactions |
| **Transactions** | The 7 accounts' transactions in one feed by date (called Activity in the code, at `/activity`); transfers are listed with a ⇄ mark but don't count as income or spending |
| **Insights** | Cash flow trends, where the money goes, comparisons with earlier periods and what drove the change, by day, week, month or year |
| **Ask Fintrack** | Conversational analysis of all transactions with Claude |
| **Accounts** | Balances, credit limits, each card's statement and due date, connection status, renewing consent |
| **Rules** | Category rules; changing a category by hand can make one in a click |

Definitions:

- **Income MTD**: the sum of `flow_type = income` from the 1st of this month to today
- **Spending MTD**: the outflows with `flow_type = expense` from the 1st of this month to today, less refunds (positive amounts in spending categories). Pending transactions count
- **Net Cash Position**: the current balances of the deposit accounts, less the current balances owed on the credit cards
- **Card payments**: each card's statement balance, minimum payment and due date come from the bank (see section 3). "Paid" is the money paid into the card since the statement date: the larger of the card payments in the ledger and the last payment the bank reports, as the ledger may have put a payment somewhere else. A statement is paid once that covers its balance, and overdue when the due date passes before then, or when the bank marks it overdue. The Overview shows a calendar: from this week's Monday, one tile a day, for at least 5 and at most 7 weeks, far enough to reach the last due date. A day with payments due is shaded by how much is still owed that day: the chart blue mixed into the tile color at 18%, 34%, 50% and 66%, four steps, bluer the more is owed. Mixed rather than solid, it stays soft in light and dark mode alike, and body text stays readable on every step (contrast at least 5.5:1). A paid day gets a check mark, today an outline, and overdue cards a notice of their own above the calendar. Clicking a day lists the cards due that day beside the calendar (below it on a phone), with the total still owed next to the heading
- **Comparisons**: income and spending are compared with the same period last month (from the 1st of last month to the same day; a day beyond the end of last month becomes its last day). Net cash position is compared with the same day last month. Aggregators only provide current balances, so a past day's position is worked out backwards: the current position less the sum of all posted transactions since that day. A transfer between two connected accounts goes out of one and into the other, so it cancels out. When last month's value is zero or negative, no percentage is shown
- **Cash flow forecast** (`forecast.py`): the last 60 days of net cash position, or of the cash in the bank alone, worked backwards as above, then 60 days ahead, day by day from today's balances. Recurring transactions are found in the last 180 days: the same merchant or description (its first words, numbers left out) in the same direction, at least three times at a steady rhythm (weekly, every two weeks, twice a month or monthly, with 75% of the gaps fitting) and not stopped; each lands on its next expected date at the median of its last three amounts, and a monthly one keeps its day of the month, so rent paid a day early doesn't shift the next one. Everyday spending is the rest of the spending, at the median weekly rate of the last 13 weeks (a one-off like a flight doesn't inflate it), spread over the days and split between accounts as it has been. Card payments only move the cash in the bank, and follow the payment calendar: what is left of each statement is paid in full on its due date, and the next one, the charges between statements, a month later. When the bank leaves out the statement's amount, the whole balance is paid; when it leaves out the statement's date, it is taken as 25 days before the due date. The cash in the bank is the first view, since net cash position already subtracts card balances and doesn't move when they're paid. Income that doesn't recur isn't projected, so the forecast leans low

**Languages**: English is the source language, and the web app also comes in Simplified Chinese. The switch is at the bottom of the sidebar (at the end of the top bar on a phone); the browser remembers the choice, and the first visit follows the browser's language. Every string the web app shows is in `web/src/i18n/en.ts`; a translation such as `zh.ts` must have the same shape, so the type check fails until it is complete. Dates and comparisons are phrased per language as well. Category names are stored in English and translated by category id; the few server error messages a user can run into are translated by their English text. The command line, logs and API stay in English.

## 2. Architecture

```
BOA · Chase · Amex
   │  OAuth (bank passwords are only typed into Plaid's pop-up; Fintrack never sees them)
   ▼
Plaid API
   │  /transactions/sync, daily (incremental, by cursor)
   ▼
┌─ Fintrack backend · single process · 127.0.0.1 ──────────
│  Scheduler ──► Sync Engine ──► Connectors (Plaid | CSV)
│                    │
│                    ▼
│  Enrichment: normalize → transfer match → categorize ──► Claude API
│                    │
│                    ▼
│  SQLite: raw │ ledger │ enrichment │ analytics views
│                    ▲
│  Analytics API ────┤
│  Ask Agent ────────┘ read-only SQL ──────────────────► Claude API
└──────────────┬────────────────────────────────────────────
               │  REST + SSE
        Browser (React SPA)
```

- **One process**: a single FastAPI process serves the API and the frontend and runs the scheduled jobs, managed by launchd. It only listens on 127.0.0.1 and checks the Host header, against DNS rebinding.
- **SQLite (WAL mode)**: the schema is in numbered SQL migration files, with the version kept in `PRAGMA user_version`. Migrations only ever move forward, and before migrating a database that holds data, the server copies it to `data/backups/` (the latest 5 copies are kept). Data access is plain SQL, with no ORM: the analytics views are SQL anyway, and they're also what Claude queries for Ask.
- **Polling, not webhooks**: running locally, there's no public address for Plaid's webhooks to reach.

## 3. Data source: Plaid Trial

- Each bank sign-in is one Item. Trial allows 10 in total, **counted cumulatively: removing one doesn't give it back**. A connection that drops off is always repaired through Link's update mode, never removed and connected again.
- Link parameters: `products=["transactions"]`, `optional_products=["liabilities"]`, `transactions.days_requested=730` (which can't change once the Item exists). `auth` isn't requested, so full account and routing numbers never enter the system.
- Each sync also calls `/liabilities/get` for each credit card's statement balance, statement date, minimum payment, due date and last payment, kept in `card_statements` (one row per card, overwritten each time). When the bank doesn't support it, the Item has no credit cards, or the data isn't ready yet, this step is skipped without affecting the transaction sync.
- In a desktop browser, OAuth completes in a pop-up, so no `redirect_uri` is needed.
- Production requires an approved Trial application (since 2026-05-20, Trial can use every OAuth bank without the security questionnaire) and a Data Transparency use case chosen in Link customization.
- OAuth consent expires: every 12 months at BOA and Amex; at Chase after the 6 months or 1 year the user picks when consenting ("always" is only offered to apps with Auth). The Item then goes to `ITEM_LOGIN_REQUIRED` and is repaired in update mode.
- Sandbox and Production use separate database files (`data/fintrack-sandbox.db` and `data/fintrack-production.db`).
- A connector only fetches and normalizes, producing records that don't depend on the source (`AccountRecord`, `TransactionRecord`). Later, a bank could move to Teller, or a CSV import could fill in history older than 2 years.

## 4. Storage

| Layer | Tables | Rules |
|---|---|---|
| Raw | `raw_events` | Every API response as received, append-only |
| Ledger | `items` `accounts` `transactions` `balance_snapshots` `card_statements` `sync_runs` | The cleaned-up, unified ledger |
| Enrichment | `categories` `transaction_enrichment` `transaction_overrides` | Automatic categories are recomputed in full after every sync; the user's edits are kept apart, and a sync never overwrites them |
| Views | `v_ledger` | Overview, Transactions, Insights, the forecast and Ask all read only this view, so every page counts the same way. Views are code: `views.sql` creates them afresh whenever the database is opened, and migrations only hold tables and data |

Conventions:

- **Amounts**: integer cents, signed from your point of view: money in is positive, money out negative. Plaid's raw data is the other way round, so the sign is flipped on the way in.
- **Dates**: `transaction_date` is the `authorized_date`, or the `posted_date` when there's none. Every figure goes by it, so a card swiped on 10/31 that posts on 11/2 counts in October.
- **Time formats**: timestamps are UTC ISO-8601 and dates `YYYY-MM-DD`; balance snapshots go by local date, one row per account per day.
- **No hard deletes**: a transaction Plaid withdraws (for example a pending one that has posted) only gets `removed_at`.
- **No secrets in the database**: the Plaid access tokens and all API keys are in the macOS Keychain (service `fintrack`).
- **One definition of the basic quantities**: income and spending per day (flows) and cash, card debt and net cash position on a day (positions) are defined in `measures.py`, and every page that shows them asks there.
- **The category decides the flow type**: every category is expense, income or transfer, and `flow_type` follows it. So the user only ever changes the category; changing it to Between accounts, say, marks the transaction as a transfer. A positive amount in a spending category is a refund and offsets spending.
- **When a pending transaction posts**: Plaid replaces it with a new, posted transaction, and the user's edits on the pending one carry over to it.

## 5. Sync

- **When it runs**: a scheduler thread in the service process (`scheduler.py`) checks every 5 minutes and syncs if there hasn't been a successful sync since the most recent 6:00 AM. So if the Mac slept through 6:00, it catches up within minutes of waking. After a failure it retries, at least 30 minutes apart. The Accounts page also has a Sync now button, and after a new bank is connected the page polls until its 2 years of history are in.
- **Always on**: `fintrack service install` registers the service as a macOS LaunchAgent, which starts at login and restarts after a crash. It runs `fintrack serve` straight from the project's virtual environment, without uv or a shell.
- **Each Item on its own**: first `/accounts/get`, then `/transactions/sync` page after page to the end, then, in **one database transaction**, write the Raw layer, update the accounts and balance snapshots, write the transactions, mark the removed ones and advance the cursor. A crash part way through writes nothing, and the next run starts again from the old cursor.
- `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` while paging: the whole round starts again from its first cursor.
- `NOT_READY` comes with an empty `next_cursor`: the old cursor stays, and the next run retries.
- `ITEM_LOGIN_REQUIRED`: the Item is marked `login_required`, and the page offers Sign in again (update mode).
- Only one sync runs at a time in the process, and running one again gives the same result (idempotent).

## 6. Categories and analysis

### Automatic categories (Phase 1, `enrich.py`)

The taxonomy has two levels and about 60 categories, defined in the migration `0002_enrichment.sql` (named in English since `0005`); only the lowest level can be given to a transaction. The rules are tried from the top, and the first match wins:

1. Transactions on **non-cash accounts** (loans, investments): transfers, outside income and spending
2. **Person-to-person apps** (Zelle, Venmo, Cash App, Apple Cash, and PayPal when no merchant is recognized): money in is Money paid back, which offsets spending; money out is Payments to people, which counts as spending. A payment to a merchant through PayPal stays in that merchant's category
3. **Credit card payments**, recognized at both ends: the payment arriving on the card (such as "AUTOMATIC PAYMENT - THANK YOU"), and the payment leaving a deposit account (such as "CHASE CREDIT CRD AUTOPAY", "AMERICAN EXPRESS ACH PMT", "payment to CRD 7781")
4. **Money into a deposit account**: a description with payroll, tax refund or interest keywords makes it Salary, Tax refunds or Interest income
5. **Plaid's category**, mapped by prefix to our own, for both PFC v1 and v2. The direction of the money is checked afterwards: money out can't be income, and money into a credit card is a refund or cashback, not income either
6. **Fallback**: money into a deposit account is Other income, money into a credit card is Cashback & credits, and money out is Uncategorized

**Transfer matching**: between two different connected accounts, two transactions of equal amounts in opposite directions, posted no more than 5 days apart, are paired; both become transfers and record each other. At least one side must already be recognized as a transfer, and the other must show signs of one too, so that a refund of the same amount isn't paired by mistake. Among several candidates, one also recognized as a transfer is preferred. Loan payments: if the purchase was financed by a lender we haven't connected (a mortgage, car loan, student loan, buy now pay later), the payments count as spending; otherwise it's only borrowed money moving between accounts, a transfer.

Plaid's categories are only a hint. In Sandbox, `Sweetgreen inc payroll ppd id` is a payroll deposit but came labelled `FOOD_AND_DRINK_RESTAURANT`, and the card payment "Payment Thank You" came labelled `INCOME`. So `flow_type` and the category are both decided with the `original_description` in view.

### Category rules (Phase 2, `rules.py`)

- **Precedence**: an edit on a single transaction > your rules > the automatic rules above. Phase 3's Claude categories come after the automatic rules and only handle transactions those can't place either.
- **A rule is a condition and a category.** The condition is a merchant name (matched whole) or a keyword in the description (both the bank's original description and Plaid's name count). Matching ignores case and extra spaces, and a rule can be limited to money in or to money out. When several rules match a transaction, the most specific wins: merchant rules before keyword rules, longer keywords before shorter ones, rules with a direction before rules without, newer rules before older ones.
- There's one rule per condition (compared ignoring case): saving the same condition again changes its category.
- Whenever a rule or an edit changes, every transaction is categorized again, so rules apply to past transactions too.
- **With transfer matching**: matching never overrides a category you set. A transaction you made a transfer can still be paired with its other half on another account, which then becomes a transfer too; changing one side of a pair to spending splits the pair.
- **Making a rule from a transaction**: when changing its category, check "Use this category for similar transactions". The rule matches the merchant name when there is one, and otherwise the first few words of the description. Spending rules default to both directions, so refunds land in the same category as the purchases; income and transfer rules default to this transaction's direction. Once the rule exists, a category set by hand on this transaction gives way to it.

### Analysis (Phase 2, `insights.py`)

- **Granularity**: day, week (Monday to Sunday), month or year. The trend chart shows the last 30 days, 26 weeks or 24 months, or every year since the data begins. Periods that ended before the first transaction aren't shown.
- **Definitions**: income, spending and net (income minus spending) are counted as on the Overview: transfers don't count, pending transactions do.
- **Comparisons**, three kinds: the previous period; the same period last year (dates moved back a year, with February 29 taken as the 28th); the average of the previous 3 periods. A period still running is compared with the same days of the earlier ones, such as October 1–28 against September 1–28, cut off at the end of a shorter month; a finished period is compared whole.
- **Breakdowns** are by category group, expand to subcategories, and have a share column. Clicking a category opens Transactions filtered to that category and the period's dates.
- **The spending donut** shows proportions at a glance: this period's 5 biggest category groups get slices of their own, and the rest share one gray slice. The past year's 5 biggest groups each have a fixed color, which stays the same from period to period; a group new to this period's top 5 borrows a color left free. Slices go round in color order, an order whose neighbouring colors stay distinct for color-blind readers. Shares are of spending before refunds and reimbursements; a group that got back more than it spent in the period has no slice, and a note below the chart says so.
- **What drove the change** lists both the groups that went up most and those that went down most, since a small net change can hide big swings in a few categories.

## 7. Claude categories and Ask Fintrack (Phase 3)

Both call Claude and share the privacy gateway of section 8, so they're built together.

- **Claude categories**: transactions the automatic rules leave uncategorized go to Claude. Structured outputs guarantee a valid category; only redacted description templates are sent, and results are cached locally by template. Low-confidence results go to a list for you to confirm.
- Claude gets a read-only SQL tool (over the redacted view `v_ai_ledger` only, on a read-only connection, with limits on the rows returned and the run time) plus a few summary tools; answers stream, and conversations are kept locally.
- The schema, definitions, taxonomy and account aliases go in the system prompt, cached with prompt caching.
- Only query results from the redacted view leave this Mac; in schema-only mode, results don't leave it at all. See section 8.
- The default model is `claude-opus-5-5`; categorization can use the cheaper `claude-haiku-5-5`.

## 8. Privacy

The principle: real data stays on this Mac by default. Plaid fetches the data and can see all of it, the one exception. Data could only reach Anthropic by two paths, and both follow the rules below.

### Data classes

| Class | What | Sent to Anthropic? |
|---|---|---|
| Identity | Your name, the names of people on the other end of transfers, account and card numbers down to the last digits, addresses, phone numbers, email, the reference numbers in descriptions (ID, Conf#, PPD ID and so on), your notes | Never |
| Location | Merchant addresses, cities, ZIP codes, coordinates | Never |
| Transaction details | A transaction's date, amount and merchant name; account balances | Not by default; with the AI features on, only the least each feature needs |
| Aggregates | Category totals, monthly trends, counts | Once the AI features are on |

### Path 1: Claude Code during development

Everything Claude Code reads is sent to Anthropic, so development only touches code and Sandbox data:

- The rules are in `CLAUDE.md`: don't read `data/` or the Keychain, and don't access the production server. The UI is checked on made-up demo data only, generated by `scripts/seed_demo.py` into `.dev-data/`, with the demo server on port 8788.
- Backstops: deny rules in `.claude/settings.json` block reading `data/`, and the PreToolUse hook `.claude/hooks/private_data_guard.py` blocks commands and browser actions that would touch the database, the Keychain or port 8787.
- `fintrack status` only prints connection status, account types, and each account's transaction count and date range, without account names, last digits or balances.
- Categories aren't tuned through Claude Code: you fix wrong categories in the web app, and a fix can become a rule (Phase 2) that applies from then on.
- Turning off Model Improvement in claude.ai's privacy settings keeps development conversations out of training.

### Path 2: the AI features in the app (Phases 2 and 3)

- Off by default. Without an `ANTHROPIC_API_KEY`, the app sends no requests at all.
- Every request goes through one gateway module (`privacy.py`): it's cut down to what the feature needs, then redacted, and the exact content sent is recorded in the local `ai_requests` table, which the web app can show at any time.
- Categorization (Phase 2): only deduplicated description templates, merchant names, Plaid categories and the direction of the money; no amounts, dates or accounts. Results are cached locally by template, so each kind of description is sent once.
- Ask (Phase 3): Claude can only query the dedicated view `v_ai_ledger`, which holds just the date, amount, category, flow type, merchant name and an account alias (such as "Chase credit card 2"), with no original descriptions, account digits, locations or notes. The people on the other end of person-to-person transfers become pseudonyms such as "Contact A", and the mapping stays local. There's also a schema-only mode: Claude only writes the SQL, which runs on this Mac and shows you the results directly, without sending them back to Claude.
- The app calls Claude through the API, under the commercial terms: data isn't used for training, and inputs and outputs are deleted from Anthropic's backend within 30 days, except where a usage policy violation or the law requires keeping them.

### On this Mac

The database isn't encrypted separately; it relies on macOS FileVault full-disk encryption. `data/` and `.env` are in `.gitignore`, so they never get into git.

## 9. Phases

- [x] Phase 0 code: Plaid connector, sync engine, Raw and Ledger storage, a connection debug page, the CLI
- [x] Phase 0 Sandbox acceptance (2026-10-28): 7 accounts and 316 transactions stored, signs checked against the raw data, Link opens
- [x] Phase 0 real-bank acceptance (2026-10-28): BOA, Chase and Amex connected through OAuth, history synced. Some accounts have less than 2 years of history (all the bank provides, or a card opened later); a CSV import can fill it in when needed
- [x] Phase 1 MVP code (2026-10-28): scheduled sync and the launchd service, enrichment (flow types, transfer matching, rule-based categories, user edits), the React frontend (Overview, Transactions, Accounts)
- [x] Privacy safeguards (2026-10-28): Claude Code's access rules and backstops, a `fintrack status` without personal data, development on Sandbox only
- [x] Phase 2 code (2026-10-28): category rules and "Use this category for similar transactions", the Insights page, a date filter on Transactions, made-up demo data for development. Categories on real data are fixed by you in the web app, which is also how the Phase 1 rules are tuned
- [ ] Phase 3: Claude categories and Ask Fintrack
- [ ] Account management: adding or removing cards on a connected bank (account selection in update mode), leaving an account out of the figures, reminders before consent expires, CSV import for older history
- [x] Credit card payments (2026-11-01): card statements (Liabilities) fetched on every sync, statements and due dates on the Accounts page, the cards still to pay on the Overview
- [x] English as the source language (2026-11-01): the web app comes with a Chinese translation; the command line, logs and API are in English; the docs come in both languages
- [x] Releases (2026-11-07): version tags publish a GitHub release through CI, and `fintrack update` installs the latest stable release, a given one, or the development version
- [x] Cash flow forecast (2026-11-14): net cash position and the cash in the bank two months ahead, from recurring income and bills, everyday spending and card statements
- [ ] Later: subscriptions and recurring charges, unusual transaction alerts, budgets, investment accounts
