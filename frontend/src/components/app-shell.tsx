"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

const navigation = {
  en: {
    single: [
      { href: "/", label: "Dashboard" },
      { href: "/clients", label: "Clients" }
    ],
    settings: {
      label: "Settings",
      children: [
        { href: "/settings", label: "Delivery methods" },
        { href: "/servers", label: "Servers" },
        { href: "/topologies", label: "Topologies" },
        { href: "/jobs", label: "Jobs" }
      ]
    }
  },
  ru: {
    single: [
      { href: "/", label: "Дашборд" },
      { href: "/clients", label: "Клиенты" }
    ],
    settings: {
      label: "Настройки",
      children: [
        { href: "/settings", label: "Способы доставки" },
        { href: "/servers", label: "Серверы" },
        { href: "/topologies", label: "Топологии" },
        { href: "/jobs", label: "Задачи" }
      ]
    }
  }
};

export function AppShell({
  children,
  sidebarExtra
}: Readonly<{ children: React.ReactNode; sidebarExtra?: React.ReactNode }>) {
  // Shared admin shell for all authenticated pages; mode-specific UI is rendered inside the page content.
  const pathname = usePathname();
  const { logout, token } = useAuth();
  const { locale, setLocale } = useLocale();
  const [settingsOpen, setSettingsOpen] = useState(
    pathname.startsWith("/settings") || pathname.startsWith("/servers") || pathname.startsWith("/topologies") || pathname.startsWith("/jobs")
  );
  const copy = locale === "ru"
    ? { title: "Навигация", logout: "Выйти" }
    : { title: "Navigation", logout: "Logout" };
  const nav = navigation[locale];

  return (
    <div className="layout">
      <div className="shell app-shell">
        <aside className="sidebar">
          <div className="sidebar-section sidebar-section-brand">
            <div className="brand-block">
              <span className="eyebrow">AWG Control Panel</span>
              <h1>{copy.title}</h1>
            </div>
            <div className="language-switcher" role="group" aria-label="Language switcher">
              <button
                type="button"
                className={locale === "ru" ? "lang-button active" : "lang-button"}
                onClick={() => setLocale("ru")}
              >
                RU
              </button>
              <button
                type="button"
                className={locale === "en" ? "lang-button active" : "lang-button"}
                onClick={() => setLocale("en")}
              >
                EN
              </button>
            </div>
          </div>
          <div className="sidebar-section">
            <nav className="nav-list">
              {nav.single.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={pathname === item.href ? "nav-link active" : "nav-link"}
                >
                  {item.label}
                </Link>
              ))}
              <div className="nav-group">
                <button
                  type="button"
                  className={
                    settingsOpen || pathname.startsWith("/settings") || pathname.startsWith("/servers") || pathname.startsWith("/topologies") || pathname.startsWith("/jobs")
                      ? "nav-link nav-toggle active"
                      : "nav-link nav-toggle"
                  }
                  onClick={() => setSettingsOpen((current) => !current)}
                >
                  <span>{nav.settings.label}</span>
                  <span className="nav-caret">{settingsOpen ? "−" : "+"}</span>
                </button>
                {settingsOpen ? (
                  <div className="nav-sublist">
                    {nav.settings.children.map((item) => (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={pathname === item.href ? "nav-link nav-sublink active" : "nav-link nav-sublink"}
                      >
                        {item.label}
                      </Link>
                    ))}
                  </div>
                ) : null}
              </div>
            </nav>
          </div>
          {sidebarExtra ? <div className="sidebar-section sidebar-extra">{sidebarExtra}</div> : null}
        </aside>
        <section className="content-panel">
          {token ? (
            <div className="content-topbar">
              <button type="button" className="secondary-button" onClick={logout}>
                {copy.logout}
              </button>
            </div>
          ) : null}
          {children}
        </section>
      </div>
    </div>
  );
}
