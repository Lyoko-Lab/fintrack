# Fintrack · Working agreement for Claude Code

A personal finance system. The design is in docs/DESIGN.md and usage in README.md. Talk to the user in Chinese.

## Privacy: real financial data stays out of the conversation

The user has connected real bank accounts. Everything Claude Code reads (file contents, command output, screenshots, web pages) is sent to Anthropic, so development only touches code and Sandbox test data:

- Don't read any file under `data/`: the production and Sandbox databases, their `-wal`/`-shm` files, the logs. Don't query the ledger through sqlite3, Python or `fintrack.db` either.
- Don't read the Keychain entries whose service is `fintrack`.
- Don't access the production server (127.0.0.1:8787): no curl, no opening it in the browser pane or in Chrome, no screenshots.
- Only run commands whose output holds no personal information: `fintrack status` (connection status, each account's transaction count and date range), `fintrack secrets list`, `fintrack service status`, `uv run pytest`. A new command that reads real data has to keep to this in its output too.
- Check the UI on made-up demo data only: run `uv run python scripts/seed_demo.py`, then start `fintrack-demo` (port 8788) and `web-dev` (port 5173, with `/api` forwarded to 8788) from `.claude/launch.json`.
- When something can only be judged from real data, ask the user to look at it or fix it in the web app, rather than reading the data. Tuning categories works the same way: the user fixes them in the web app, and a fix can become a rule.

The deny rules in `.claude/settings.json` and the `.claude/hooks/private_data_guard.py` hook are backstops, but they can't catch every way of writing a command; the rules above are what count.

## Development

- Backend tests: `uv run pytest`. Frontend type check: `npm --prefix web run typecheck`.
- `web/dist` is the frontend the production service is serving, so building it changes the page the user is using right away. To check that it builds, output to a scratch directory: `npm --prefix web exec -- vite build web --outDir <scratch directory>`. Deploying a new version (building `web/dist`, restarting the service) needs the user's go-ahead first.
- Amounts are integer cents, with money in positive. A schema change gets a new numbered migration file; existing migrations are never edited. Views aren't in migrations: they live in `src/fintrack/views.sql`, created afresh whenever the database is opened.
- Income, spending (`daily_flows`, `total_flow`) and cash, card debt and net cash position on a day (`positions`) come from `src/fintrack/measures.py`; build on those rather than querying them again.
- After `fintrack update`, the checkout may sit on a release tag with a detached HEAD: `git switch main` before committing. Keep the "Unreleased" section of both changelogs up to date with user-visible changes; releasing is described in README.md.
- English is the source language of the code, comments, command line and docs. Every string the web app shows goes in `web/src/i18n/en.ts`, with its translation in `zh.ts` (category names are translated there too, by id). A doc that changes gets its `.zh-CN.md` version changed with it.
