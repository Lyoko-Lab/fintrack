# Fintrack

English | [简体中文](README.zh-CN.md)

A personal finance system that runs on your Mac. Every day it syncs your bank transactions into one ledger, tells income, spending and transfers apart, and shows it all in a local web app: headline numbers, a transaction feed, insights and credit card due dates. The design is in [docs/DESIGN.md](docs/DESIGN.md).

Status: **Phase 2**. Automatic sync, transfer matching, automatic categories plus your own category rules, and credit card statements. The web app has five pages (Overview, Transactions, Insights, Rules and Accounts), in English or Chinese.

## Setup

You need [uv](https://docs.astral.sh/uv/) and Node.js:

```bash
uv sync
```

```bash
npm --prefix web install
```

```bash
npm --prefix web run build
```

Run the last command again whenever the web app's code changes.

## 1. Sign up for Plaid and store the keys

1. Sign up at <https://dashboard.plaid.com/signup> and choose **Personal use**. Only teams created after 2026-04-15 can use the free Trial plan, which includes OAuth banks such as Chase and Bank of America.
2. Find your `client_id` and Sandbox `secret` under **Developers → Keys** in the Dashboard.
3. Store them in the macOS Keychain. Don't put the value on the command line: run the command, paste the value at the prompt and press Enter. Nothing shows while you paste, and the value stays out of your shell history and out of files on disk:

```bash
uv run fintrack secrets set PLAID_CLIENT_ID
```

```bash
uv run fintrack secrets set PLAID_SECRET_SANDBOX
```

## 2. Try it in Sandbox

All in one command (connect a test bank → fetch its data → print the result):

```bash
uv run fintrack sandbox-link
```

Or go through the browser, the same way you'll connect real banks later:

```bash
uv run fintrack serve
```

Open <http://127.0.0.1:8787>, click **Connect a bank** on the Accounts page, choose First Platypus Bank, and sign in with the username `user_transactions_dynamic` and any password.

## 3. Connect real banks (Production)

### Turn on Production in the Plaid Dashboard

1. Apply for the Trial plan at <https://dashboard.plaid.com/trial-plan> and wait for Plaid to approve it, which can take a few business days. Until then, every Production page in the Dashboard says Not available. **Don't click "Get production access"**: that applies for a paid plan, and once you've applied there's no going back to Trial.
2. In the Data Transparency section of the [Link customization page](https://dashboard.plaid.com/link/data-transparency-v5), choose the use case **Track and manage your finances**, then click Publish. Without a use case, Link won't open in Production.
3. On the [OAuth institutions](https://dashboard.plaid.com/settings/compliance/us-oauth-institutions) page, check that Bank of America, Chase and American Express are available. The Trial plan needs no security questionnaire or company profile, so it's normal for the page to say they're incomplete.
4. Copy the Production `secret` from **Developers → Keys**. The `client_id` is the same in both environments, so there's no need to store it again.

### Switch to Production

```bash
uv run fintrack secrets set PLAID_SECRET_PRODUCTION
```

```bash
printf 'FINTRACK_ENV=production\n' > .env
```

Then register the background service (section 4), or run `uv run fintrack serve` in the foreground. When the bottom of the sidebar says **Live accounts**, you're on Production.

### Connect your banks

Open <http://127.0.0.1:8787>, click **Connect a bank** on the Accounts page, and connect Bank of America, Chase and American Express in turn, each only once:

- The bank's sign-in page opens in a pop-up window. If the browser blocks it, allow pop-ups for 127.0.0.1. Your bank password is only ever typed into the bank's own page; Fintrack never sees it.
- **Select every card on the bank's consent page**: the debit and credit cards at BOA, all 3 cards at Chase, both cards at Amex.
- Chase asks how long access should last and has no default; 1 year is a good choice.
- Once connected, Fintrack fetches 2 years of history, which shows up under Transactions a few minutes later.

Consent expires: BOA and Amex ask for it again every 12 months, Chase after the period you chose. The Accounts page then says **Sign-in needed**; click **Sign in again** to fix it.

> **The Trial plan allows 10 connections in total, counted cumulatively: removing one doesn't give it back.** When a connection drops off, fix it with **Sign in again** on the page; don't remove it and connect again.
>
> **The Keychain entries with service `fintrack` hold each bank's access token.** If they're deleted, the bank has to be connected again, which uses up another connection.

## 4. Keep it running in the background

As a macOS background service, Fintrack starts when you log in, restarts if it crashes, and syncs every day at 6:00 AM. If your Mac was asleep at 6:00, it catches up when it wakes:

```bash
uv run fintrack service install
```

From then on, just open <http://127.0.0.1:8787>. `uv run fintrack service status` shows how the service is doing, and `uv run fintrack service uninstall` removes it. The log is at `data/logs/server.log`. While the service is running, don't also start `fintrack serve` by hand, or the two will fight over the same port.

To update, run:

```bash
uv run fintrack update
```

It pulls the latest code from GitHub, installs any new dependencies, builds the web app and restarts the service on the new code, then checks the service stays up. If the database schema has changed, the service migrates it when it starts. Commits you made locally are deployed too. The update stops before changing anything if the checkout has uncommitted changes or has diverged from GitHub, and a failed build leaves the running app as it was.

## Language

The web app comes in English and Simplified Chinese. Switch at the bottom of the sidebar (at the end of the top bar on a phone); the browser remembers your choice, and the first visit follows the browser's language. The command line, logs and API messages are in English.

## Commands

| Command | What it does |
|---|---|
| `uv run fintrack serve` | Starts the web app at <http://127.0.0.1:8787> in the foreground, with the daily sync |
| `uv run fintrack sync` | Syncs every bank now |
| `uv run fintrack status` | Shows the connections, and each account's transaction count and date range (no account names, last digits or balances) |
| `uv run fintrack secrets list` | Shows which secrets are set (not their values) |
| `uv run fintrack service install` | Registers the background service, which starts when you log in |
| `uv run fintrack update` | Updates to the latest code, rebuilds the web app and restarts the service |
| `uv run fintrack --version` | Shows the installed version |
| `uv run pytest` | Runs the backend tests |
| `uv run python scripts/seed_demo.py` | Writes two years of made-up transactions to `.dev-data/`, for development without real data |
| `FINTRACK_ENV=sandbox FINTRACK_DATA_DIR=.dev-data FINTRACK_PORT=8788 uv run fintrack serve` | Starts a demo server on the made-up data (port 8788) |
| `npm --prefix web run dev` | Runs the web app in development mode at <http://localhost:5173>, with hot reload; `/api` goes to the demo server on port 8788 |

Data lives in `data/`, which is in `.gitignore`. Sandbox and Production each have their own database file, so test data never mixes into your real ledger.

For the privacy design, see section 8 of [docs/DESIGN.md](docs/DESIGN.md): real data stays on this Mac by default, and developing with Claude Code doesn't read it either (the rules are in [CLAUDE.md](CLAUDE.md)).

## License

Fintrack is free software under the [GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`). You can use, study, change and share it. If you distribute a modified version, or let other people use one over a network, you have to offer them its source code under the same license.
