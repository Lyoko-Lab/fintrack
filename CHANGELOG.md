# Changelog

English | [简体中文](CHANGELOG.zh-CN.md)

What changed in each release. Versions follow [semantic versioning](https://semver.org/); before 1.0, a new minor version (0.x.0) may change anything. Each section becomes the notes of its GitHub release.

## Unreleased

- `fintrack update` goes to the latest stable release by default. `fintrack update 0.2.0` goes to a given release, and `fintrack update --dev` follows the latest code on GitHub. It won't move to a version older than your database's last migration.
- Pushing a version tag publishes a GitHub release once the tests and the build pass, with its notes taken from this changelog.

## 0.1.0 - 2026-11-07

The first release of Fintrack, a personal finance system that runs on your Mac. It syncs your bank and credit card transactions every day into one ledger on your own machine, tells income, spending and transfers apart, and shows it all in a local web app.

- **Bank sync through Plaid**: OAuth banks such as Bank of America, Chase and American Express, with 2 years of history and a daily sync at 6:00 AM. Access tokens stay in the macOS Keychain.
- **One ledger**: transactions from every account in one feed; transfers between your accounts and credit card payments are matched and kept out of income and spending.
- **Categories**: about 60 categories, set automatically, plus your own rules ("merchant is…", "description contains…") that also recategorize past transactions. A category you set by hand always wins.
- **Insights**: income, spending and net by day, week, month or year, compared with the previous period, the same period last year or a 3-period average, with a spending breakdown by category.
- **Credit cards**: each card's statement, minimum payment and due date, and a calendar of upcoming payments on the Overview.
- **English and Simplified Chinese**, switchable in the sidebar.
- **Runs in the background** as a macOS LaunchAgent, and `uv run fintrack update` updates and redeploys in one step.
- **Private by design**: the server only listens on 127.0.0.1, and your data never leaves your Mac apart from Plaid fetching it.
