// Three fixed pages don't need a routing library: the path lives in history, and
// components re-render on popstate.
import { useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

export const ROUTES = {
  overview: "/",
  activity: "/activity",
  accounts: "/accounts",
} as const;

export type Route = keyof typeof ROUTES;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname);
  return (Object.keys(ROUTES) as Route[]).find((route) => ROUTES[route] === path) ?? "overview";
}

export function navigate(route: Route): void {
  if (window.location.pathname !== ROUTES[route]) window.history.pushState(null, "", ROUTES[route]);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
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
