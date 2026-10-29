// A handful of fixed pages don't need a routing library: the path lives in history, and
// components re-render on popstate. A page can keep its view settings in the query string
// (replaceQuery), so Back and Forward return to it as it was left.
import { useEffect, useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

export const ROUTES = {
  overview: "/",
  activity: "/activity",
  insights: "/insights",
  rules: "/rules",
  accounts: "/accounts",
} as const;

export type Route = keyof typeof ROUTES;
type Params = Record<string, string | undefined>;

// Scroll positions are restored by hand (useScrollRestoration): the browser's own restoration
// runs before the page has re-rendered for the history entry it went back to.
if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function withQuery(path: string, params: Params): string {
  const search = new URLSearchParams(Object.entries(params).filter((entry): entry is [string, string] => Boolean(entry[1])));
  return path + (search.size ? `?${search}` : "");
}

const here = () => window.location.pathname + window.location.search;

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname);
  return (Object.keys(ROUTES) as Route[]).find((route) => ROUTES[route] === path) ?? "overview";
}

export function navigate(route: Route, params: Params = {}): void {
  // A link to the page already open keeps that page's settings; it only scrolls back up.
  const staying = ROUTES[route] === window.location.pathname && Object.values(params).every((value) => !value);
  const url = staying ? here() : withQuery(ROUTES[route], params);
  if (here() !== url) {
    // Remember how far down this page was, for when the user comes back to it.
    window.history.replaceState({ ...window.history.state, scrollY: window.scrollY }, "");
    window.history.pushState(null, "", url);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

/** Record the open page's view settings in its URL, without adding a history entry. */
export function replaceQuery(params: Params): void {
  const url = withQuery(window.location.pathname, params);
  if (here() !== url) window.history.replaceState(window.history.state, "", url);
}

/** On Back and Forward, scroll to where that page was left, once it has re-rendered. */
export function useScrollRestoration(): void {
  useEffect(() => {
    const onPopState = (event: PopStateEvent) => {
      const scrollY = (event.state as { scrollY?: number } | null)?.scrollY;
      if (scrollY !== undefined) requestAnimationFrame(() => window.scrollTo(0, scrollY));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
}

interface LinkProps {
  to: Route;
  className?: string;
  current?: boolean;
  children: ReactNode;
}

export function Link({ to, className, current, children }: LinkProps) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // Let the browser handle new-tab and new-window clicks.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={ROUTES[to]} className={className} aria-current={current ? "page" : undefined} onClick={onClick}>
      {children}
    </a>
  );
}
