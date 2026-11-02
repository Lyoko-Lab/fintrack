// The web app in English or Chinese. English is the source (en.ts); a translation (zh.ts) has the
// same shape, so nothing can be left out. The choice is kept in this browser; the server has no say.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en, { type Messages } from "./en";
import zh from "./zh";

export type { Messages };
export type Lang = "en" | "zh";

/** Each language as the switcher offers it, written in that language, with its tag for <html lang>. */
export const LANGUAGES: Record<Lang, { tag: string; short: string; name: string }> = {
  en: { tag: "en", short: "EN", name: "English" },
  zh: { tag: "zh-CN", short: "中文", name: "简体中文" },
};

const MESSAGES: Record<Lang, Messages> = { en, zh };
const STORAGE_KEY = "fintrack.lang";

/** The language chosen last time, else Chinese for a browser that asks for it first, else English. */
function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "zh") return saved;
  } catch {
    // Site data can be blocked; the browser's preference still applies.
  }
  const preferred = navigator.languages?.[0] ?? navigator.language ?? "";
  return preferred.toLowerCase().startsWith("zh") ? "zh" : "en";
}

// The active language, for the plain functions that run while rendering (format.ts, categoryName).
// The app reads the context too, so it all renders again when the language changes.
let active: Lang = initialLang();

export function messages(): Messages {
  return MESSAGES[active];
}

interface I18n {
  lang: Lang;
  t: Messages;
  setLang(lang: Lang): void;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState(active);
  useEffect(() => {
    document.documentElement.lang = LANGUAGES[lang].tag;
  }, [lang]);
  const value = useMemo<I18n>(
    () => ({
      lang,
      t: MESSAGES[lang],
      setLang: (next) => {
        active = next;
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch {
          // Not remembered, but switched for as long as the page is open.
        }
        setLangState(next);
      },
    }),
    [lang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const i18n = useContext(I18nContext);
  if (!i18n) throw new Error("useI18n() needs an <I18nProvider> above it");
  return i18n;
}

/** A category's name in the active language. The server sends English names; translations go by id. */
export function categoryName(category: { id: string; name: string }): string {
  return messages().categories[category.id] ?? category.name;
}

/** An error message from the server, translated when it is one the active language knows. */
export function serverError(message: string): string {
  return messages().errors.server[message] ?? message;
}
