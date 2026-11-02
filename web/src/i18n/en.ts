// English, the source language. A translation (zh.ts) has the same shape, typed as Messages, so the
// type check fails until every string is translated. Strings that take values are functions.
// Category names aren't here: the server sends them in English, and a translation lists its own by id.
import type { Granularity } from "../api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const UNITS: Record<Granularity, string> = { day: "day", week: "week", month: "month", year: "year" };
const RECONNECT = "Sign in again";
const APPLY_RULE = "Use this category for similar transactions";

/** "1 card", "3 cards". */
function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

const monthName = (month: number) => new Date(2000, month, 1).toLocaleString("en-US", { month: "long" });
const withYear = (text: string, year?: number) => (year ? `${text}, ${year}` : text);

const en = {
  common: {
    loading: "Loading…",
    saving: "Saving…",
    save: "Save",
    close: "Close",
    noTransactions: "No transactions yet",
    labelled: (label: string, value: string) => `${label}: ${value}`,
    list: (items: string[]) => items.join(", "),
  },
  nav: {
    label: "Main",
    overview: "Overview",
    activity: "Transactions",
    insights: "Insights",
    rules: "Rules",
    accounts: "Accounts",
  },
  shell: {
    env: { production: "Live accounts", sandbox: "Sandbox test data" },
    unreachable: (message: string) => `Can't reach the Fintrack server: ${message}`,
    language: "Language",
  },
  sync: {
    running: "Syncing…",
    last: (when: string | null) => (when ? `Last synced ${when}` : "Not synced yet"),
  },
  // The words of dates; format.ts decides which to show. Months count from 0, as in Date.
  dates: {
    day: (month: number, day: number, year?: number) => withYear(`${MONTHS[month]} ${day}`, year), // "Oct 28"
    days: (month: number, first: number, last: number, year?: number) =>
      withYear(`${MONTHS[month]} ${first}–${last}`, year), // "Oct 1–28"
    span: (from: string, to: string, year?: number) => withYear(`${from} – ${to}`, year), // "Sep 29 – Oct 3"
    withWeekday: (day: string, weekday: number) => `${WEEKDAYS[weekday]}, ${day}`, // "Tue, Oct 28"
    today: (day: string) => `Today · ${day}`,
    yesterday: (day: string) => `Yesterday · ${day}`,
    time: (at: Date) => at.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }), // "6:02 AM"
    atToday: (time: string) => `today at ${time}`,
    atYesterday: (time: string) => `yesterday at ${time}`,
    at: (day: string, time: string) => `${day} at ${time}`,
    month: (month: number, year: number) => `${monthName(month)} ${year}`, // "October 2026"
    monthTick: (month: number, year?: number) => (year ? `${MONTHS[month]} ’${String(year).slice(2)}` : MONTHS[month]),
    year: (year: number) => String(year),
    weekdaysFromMonday: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
  },
  // What a period is compared with, phrased to follow "than" or "with"; title() makes one a heading.
  comparison: {
    previous: { day: "the previous day", week: "last week", month: "last month", year: "last year" },
    // For a period still running, which is set against the same stretch of the one before.
    previousSoFar: {
      day: "the previous day",
      week: "the same days last week",
      month: "the same period last month",
      year: "the same period last year",
    },
    lastYear: "the same period last year",
    average: {
      day: "the 3-day average",
      week: "the 3-week average",
      month: "the 3-month average",
      year: "the 3-year average",
    },
    title: (label: string) => label.replace(/^the /, "").replace(/^./, (first) => first.toUpperCase()),
  },
  stat: {
    up: (amount: string, label: string) => `${amount} more than ${label}`,
    down: (amount: string, label: string) => `${amount} less than ${label}`,
    flat: (label: string) => `Unchanged from ${label}`,
  },
  flow: { expense: "Spending", income: "Income", transfer: "Transfers" },
  transactions: {
    pending: "Pending",
    noDescription: "(no description)",
    uncategorized: "Uncategorized",
  },
  categories: {} as Record<string, string>,
  categorySelect: {
    notCounted: " (not income or spending)",
    all: (group: string) => `${group} (all)`,
  },
  overview: {
    title: "Overview",
    emptyTitle: "No banks connected yet",
    emptyText: "Connect your banks and credit cards to see this month's income, spending and net cash position here.",
    emptyAction: "Connect a bank",
    period: (current: string, previous: string) => `${current}, compared with ${previous}`,
    income: "Income this month",
    spending: "Spending this month",
    netCash: "Net cash position",
    sameDayLastMonth: "the same day last month",
    netCashParts: (cash: string, debt: string) => `Cash ${cash} − card balances ${debt}`,
    payments: "Upcoming card payments",
    paymentsSummary: (total: string | null, paid: number) =>
      total === null
        ? "All statements are paid"
        : `${total} left to pay${paid > 0 ? `, ${plural(paid, "card")} already paid` : ""}`,
    viewAccounts: "View accounts →",
    recent: "Recent transactions",
    viewAll: "View all →",
  },
  payments: {
    calendar: "Payment calendar",
    paid: "Paid",
    overdue: "Overdue",
    overdueBy: (days: number) => `${plural(days, "day")} overdue`,
    dueUnknown: "Due date unknown",
    dueToday: "Due today",
    dueTomorrow: "Due tomorrow",
    dueIn: (days: number) => `Due in ${plural(days, "day")}`,
    minimum: (amount: string) => `Minimum ${amount}`,
    minimumShort: (amount: string) => `Min. ${amount}`,
    statementPaid: (statement: string, paid: string) => `Statement ${statement}, paid ${paid}`,
    statementBalance: "Statement balance",
    left: (amount: string) => `, ${amount} left`,
    cards: (n: number) => plural(n, "card"),
    toPay: (amount: string) => `${amount} to pay`,
    allPaid: "all paid",
    tile: (day: string, cards: number, summary: string, overdue: boolean) =>
      `${day}: ${plural(cards, "card")} due, ${summary}${overdue ? " (overdue)" : ""}`,
    day: (heading: string, cards: number, owed: string | null) =>
      `${heading} · ${plural(cards, "card")} due${owed ? ` · ${owed} to pay` : ""}`,
    overdueList: (cards: string) => `Overdue: ${cards}`,
    undated: (cards: string) => `Due date unknown: ${cards}`,
    less: "Less",
    more: "More",
    today: "Today",
  },
  activity: {
    title: "Transactions",
    subtitle:
      "Transactions from all your accounts in one feed, newest first. Transfers are listed but don't count as income or spending.",
    search: "Search merchants, bank descriptions or notes",
    searchLabel: "Search transactions",
    type: "Type",
    allTypes: "All types",
    account: "Account",
    allAccounts: "All accounts",
    category: "Category",
    allCategories: "All categories",
    clearDates: "Remove date filter",
    clear: "Clear filters",
    noMatches: "No transactions match these filters",
    loadMore: "Load more",
  },
  insights: {
    title: "Insights",
    subtitle: "How income and spending change, and where the money goes. Transfers aren't counted.",
    period: "Period",
    granularity: { day: "Day", week: "Week", month: "Month", year: "Year" },
    compareWith: "Compare with",
    previous: { day: "Previous day", week: "Previous week", month: "Previous month", year: "Previous year" },
    metric: "Metric",
    metrics: { spending: "Spending", income: "Income", net: "Net" },
    trend: (metric: string, granularity: Granularity) => `${metric} by ${UNITS[granularity]}`,
    chartLabel: (title: string) => `${title}. Choose a period to see it in detail.`,
    showTable: "Show table",
    showChart: "Show chart",
    inProgress: " (in progress)",
    through: (day: string) => ` (through ${day})`,
    periodColumn: "Period",
    chartCaption: "Click a bar to see that period in detail below. The lighter bar is the period still in progress.",
    tableCaption: "Click a period to see it in detail below.",
    comparedWith: (label: string, periods: string[], _average: boolean) =>
      `Compared with ${label} (${periods.join(", ")})`,
    netFootnote: "Income minus spending",
    unchanged: (label: string) => `Spending is roughly unchanged from ${label}.`,
    higher: (amount: string, label: string) => `Spending is ${amount} higher than ${label}.`,
    lower: (amount: string, label: string) => `Spending is ${amount} lower than ${label}.`,
    increases: "Biggest increases:",
    decreases: "Biggest decreases:",
    others: (n: number) => plural(n, "other category", "other categories"),
    totalSpending: "Total spending",
    viewSlice: (name: string, share: string, amount: string) => `${name} ${share}, ${amount}: view these transactions`,
    offset: (name: string, net: string) => `${name} (net ${net})`,
    offsetsNote: (gross: string, offsets: string[]) =>
      `Percentages are of the ${gross} spent before refunds and reimbursements. ${offsets.join(", ")} got back ` +
      `more than was spent this period, so ${offsets.length === 1 ? "it isn't" : "they aren't"} in the chart.`,
    byCategory: { expense: "Spending by category", income: "Income by category" },
    none: { expense: "No spending this period", income: "No income this period" },
    thisPeriod: "This period",
    category: "Category",
    comparisonChart: "Comparison chart",
    share: "Share",
    change: "Change",
    expand: (name: string) => `Expand ${name}`,
    collapse: (name: string) => `Collapse ${name}`,
    viewTransactions: "View these transactions",
    viewCategory: (name: string) => `${name}: view these transactions`,
  },
  rules: {
    title: "Category rules",
    subtitle:
      "Rules override automatic categories, and a category you set on a single transaction overrides rules. Changing a rule recategorizes all past transactions right away.",
    newRule: "New rule",
    categorizeAs: "Categorize as",
    chooseCategory: "Choose a category",
    add: "Add rule",
    yours: "Your rules",
    count: (n: number) => plural(n, "rule"),
    condition: "Condition",
    category: "Category",
    appliesTo: "Applies to",
    actions: "Actions",
    transactions: (n: number) => plural(n, "transaction"),
    categoryFor: (pattern: string) => `Category for “${pattern}”`,
    delete: "Delete",
    confirmDelete: (rule: string) => `Delete the rule “${rule}”? Its transactions go back to automatic categories.`,
    empty: `No rules yet. Check “${APPLY_RULE}” when you change a transaction's category, or add one above.`,
    match: { merchant: "Merchant is", description: "Description contains" },
    direction: { inflow: "Money in only", outflow: "Money out only" },
    eitherDirection: "Money in or out",
    matchOn: "Match on",
    merchant: "Merchant name",
    keyword: "Keyword",
    directionLabel: "Direction",
    merchantExample: "e.g. Starbucks",
    keywordExample: "e.g. PAYROLL",
    hint: "Enter a merchant name or a keyword. Case doesn't matter.",
    matching: (n: number) => (n === 1 ? "1 transaction matches right now." : `${n} transactions match right now.`),
    noneMatching: "No transactions match right now.",
  },
  drawer: {
    title: "Transaction details",
    date: "Date",
    postedOn: (day: string) => ` (posted ${day})`,
    account: "Account",
    status: "Status",
    posted: "Posted",
    bankDescription: "Bank description",
    category: "Category",
    manual: "You set this category yourself.",
    automatic: (reason: string) => `Set automatically. ${reason}`,
    applyRule: APPLY_RULE,
    ruleHint:
      "This adds a rule and recategorizes past transactions too. Transactions you recategorized one by one keep their category.",
    note: "Note",
    revert: "Restore automatic category",
    saveWithRule: "Save and apply rule",
    // Why the automatic category was chosen, by enrich.py's rule codes.
    reasons: {
      userRule: (rule: string) => `Matched your rule “${rule}”.`,
      account: "It's on a loan, investment or other non-cash account, so it isn't counted as income or spending.",
      p2pIn: "Money from a person (Zelle, Venmo and the like), taken as a shared bill or expense paid back: it offsets spending.",
      p2pOut: "Money sent to a person (Zelle, Venmo and the like), counted as spending.",
      cardPayment: "Recognized as a credit card payment, which isn't counted as income or spending.",
      payroll: "The description has payroll keywords.",
      taxRefund: "Recognized as a tax refund.",
      interest: "Recognized as interest income.",
      plaid: (category: string) => `Based on Plaid's category: ${category}.`,
      direction: (category: string) =>
        `Plaid's category (${category}) didn't fit the direction of the money, so it was adjusted.`,
      pair: (account: string) =>
        `Paired as a transfer with an equal and opposite transaction on ${account}, so it isn't counted as income or spending.`,
      otherAccount: "another account",
      fallback: "No category information was available, so it was categorized by the direction of the money.",
    },
  },
  accounts: {
    title: "Accounts",
    schedule: "Syncs every day at 6:00 AM",
    syncing: "Syncing…",
    syncNow: "Sync now",
    connect: "Connect a bank",
    confirmConnect: (limit: number, used: number) =>
      `Each new bank you connect permanently uses one of your ${limit} Plaid Trial connections (${used} used so far).\n` +
      `If a bank you connected before has dropped off, fix it with “${RECONNECT}” instead.\n\nConnect a new bank?`,
    notConfigured: "Plaid keys aren't set up yet. Run these in a terminal, then reload this page:",
    cash: "Total cash",
    cardBalances: "Card balances",
    netCash: "Net cash position",
    trial: (used: number, limit: number) =>
      `Plaid Trial connections: ${used} of ${limit} used. Removing one doesn't give it back, so when a connection drops off, use “${RECONNECT}”.`,
    status: { active: "Connected", login_required: "Sign-in needed", error: "Error" },
    types: {
      depository: "Deposit",
      credit: "Credit card",
      loan: "Loan",
      investment: "Investment",
    } as Record<string, string>,
    history: {
      NOT_READY: "Plaid is preparing the data…",
      INITIAL_UPDATE_COMPLETE: "The last 30 days are in; older history is still on its way…",
    } as Record<string, string>,
    unknownInstitution: "Unknown institution",
    synced: (when: string | null) => (when ? `Synced ${when}` : "Not synced yet"),
    reconnect: RECONNECT,
    account: "Account",
    type: "Type",
    balance: "Balance",
    available: "Available",
    limit: "Credit limit",
    statement: "Statement",
    due: "Due date",
  },
  errors: {
    plaidScript: "Couldn't load Plaid Link. Check your internet connection.",
    // The server's messages are in English; a translation maps the ones a user can run into.
    server: {} as Record<string, string>,
  },
};

export type Messages = typeof en;
export default en;
