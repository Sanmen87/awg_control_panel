"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";

import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

function IconBase({
  children,
  className
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.85">
      {children}
    </svg>
  );
}

function MenuIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </IconBase>
  );
}

function LogoutIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M10 7V5a2 2 0 0 1 2-2h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5a2 2 0 0 1-2-2v-2" />
      <path d="M15 12H4" />
      <path d="m8 8-4 4 4 4" />
    </IconBase>
  );
}

const navigation = {
  en: {
    single: [
      { href: "/", label: "Dashboard" },
      { href: "/clients", label: "Clients" },
      { href: "/extra-services", label: "Extra services" }
    ],
    settings: {
      label: "Settings",
      children: [
        { href: "/servers", label: "Servers" },
        { href: "/topologies", label: "Topologies" },
        { href: "/backups", label: "Backups" },
        { href: "/web-settings", label: "Web / HTTPS" },
        { href: "/settings", label: "Delivery methods" },
        { href: "/jobs", label: "Jobs" }
      ]
    }
  },
  ru: {
    single: [
      { href: "/", label: "Дашборд" },
      { href: "/clients", label: "Клиенты" },
      { href: "/extra-services", label: "Доп сервисы" }
    ],
    settings: {
      label: "Настройки",
      children: [
        { href: "/servers", label: "Серверы" },
        { href: "/topologies", label: "Топологии" },
        { href: "/backups", label: "Бэкапы" },
        { href: "/web-settings", label: "Веб-интерфейс" },
        { href: "/settings", label: "Способы доставки" },
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
    pathname.startsWith("/settings") || pathname.startsWith("/servers") || pathname.startsWith("/backups") || pathname.startsWith("/topologies") || pathname.startsWith("/jobs")
    || pathname.startsWith("/web-settings")
  );
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const copy = locale === "ru"
    ? { title: "Навигация", logout: "Выйти", madeBy: "Сделано Sunmen87", menu: "Меню", closeMenu: "Закрыть меню" }
    : { title: "Navigation", logout: "Logout", madeBy: "Made by Sunmen87", menu: "Menu", closeMenu: "Close menu" };
  const nav = navigation[locale];

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname]);

  return (
    <div className="layout">
      <div className="shell app-shell">
        <button
          type="button"
          className={`sidebar-backdrop ${mobileMenuOpen ? "is-open" : ""}`}
          aria-hidden={!mobileMenuOpen}
          tabIndex={mobileMenuOpen ? 0 : -1}
          onClick={() => setMobileMenuOpen(false)}
        />
        <aside className={`sidebar ${mobileMenuOpen ? "is-open" : ""}`}>
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
                  onClick={() => setMobileMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
              <div className="nav-group">
                <button
                  type="button"
                  className={
                    settingsOpen || pathname.startsWith("/settings") || pathname.startsWith("/servers") || pathname.startsWith("/topologies") || pathname.startsWith("/jobs")
                    || pathname.startsWith("/backups") || pathname.startsWith("/web-settings")
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
                        onClick={() => setMobileMenuOpen(false)}
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
          {token ? (
            <div className="sidebar-section sidebar-mobile-exit">
              <button type="button" className="secondary-button" onClick={logout}>
                {copy.logout}
              </button>
            </div>
          ) : null}
        </aside>
        <section className="content-panel">
          {token ? (
            <div className="content-topbar">
              <div className="mobile-shell-bar">
                <button
                  type="button"
                  className="secondary-button mobile-nav-button"
                  aria-expanded={mobileMenuOpen}
                  aria-label={mobileMenuOpen ? copy.closeMenu : copy.menu}
                  onClick={() => setMobileMenuOpen((current) => !current)}
                >
                  <MenuIcon className="mobile-bar-icon" />
                  <span>{copy.menu}</span>
                </button>
              </div>
              <button type="button" className="secondary-button desktop-logout-button" onClick={logout}>
                {copy.logout}
              </button>
            </div>
          ) : null}
          {children}
          <footer className="app-footer">
            <span>{copy.madeBy}</span>
            <a href="https://github.com/Sanmen87/awg_control_panel" target="_blank" rel="noreferrer">
              <span aria-hidden="true">◐</span> GitHub
            </a>
          </footer>
        </section>
      </div>
    </div>
  );
}
