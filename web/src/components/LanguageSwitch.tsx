import { LANGUAGES, useI18n, type Lang } from "../i18n";

/** English or Chinese. Each option is written in its own language, so it can be found from either. */
export function LanguageSwitch() {
  const { lang, t, setLang } = useI18n();
  return (
    <div className="segmented compact" role="group" aria-label={t.shell.language}>
      {(Object.keys(LANGUAGES) as Lang[]).map((option) => (
        <button
          key={option}
          type="button"
          lang={LANGUAGES[option].tag}
          aria-label={LANGUAGES[option].name}
          title={LANGUAGES[option].name}
          aria-pressed={option === lang}
          onClick={() => setLang(option)}
        >
          {LANGUAGES[option].short}
        </button>
      ))}
    </div>
  );
}
