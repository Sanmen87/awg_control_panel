"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "ru";

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  ready: boolean;
};

const LocaleContext = createContext<LocaleContextValue | undefined>(undefined);

export function LocaleProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [locale, setLocaleState] = useState<Locale>("ru");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const savedLocale = window.localStorage.getItem("awg-locale");
    if (savedLocale === "en" || savedLocale === "ru") {
      setLocaleState(savedLocale);
    }
    setReady(true);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      ready,
      setLocale: (nextLocale) => {
        setLocaleState(nextLocale);
        window.localStorage.setItem("awg-locale", nextLocale);
      }
    }),
    [locale, ready]
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale must be used within LocaleProvider");
  }
  return context;
}

