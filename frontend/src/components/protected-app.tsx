"use client";

import { AppShell } from "./app-shell";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";
import { LoginForm } from "./login-form";

export function ProtectedApp({
  children,
  sidebarExtra
}: Readonly<{ children: React.ReactNode; sidebarExtra?: React.ReactNode }>) {
  const { token, ready } = useAuth();
  const { locale } = useLocale();
  const copy = locale === "ru"
    ? { loading: "Подготовка сессии администратора." }
    : { loading: "Preparing admin session." };

  if (!ready) {
    return (
      <main className="layout">
        <div className="shell">
          <section className="hero">
            <span className="eyebrow">Loading</span>
            <h1>{copy.loading}</h1>
          </section>
        </div>
      </main>
    );
  }

  if (!token) {
    return (
      <main className="layout">
        <div className="shell auth-shell">
          <LoginForm />
        </div>
      </main>
    );
  }

  return <AppShell sidebarExtra={sidebarExtra}>{children}</AppShell>;
}
