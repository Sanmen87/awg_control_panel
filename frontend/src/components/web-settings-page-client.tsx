"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "./api";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";
import { ProtectedApp } from "./protected-app";

type WebSettings = {
  public_domain: string | null;
  admin_email: string | null;
  web_mode: string;
  generated_nginx_config: string;
};

type WebStatus = {
  public_domain: string | null;
  web_mode: string;
  dns_ok: boolean;
  resolved_ips: string[];
  port_80_open: boolean;
  port_443_open: boolean;
  certificate_present: boolean;
  certificate_expires_at: string | null;
  detail: string | null;
};

type WebApplyResult = {
  public_domain: string | null;
  web_mode: string;
  nginx_reloaded: boolean;
  certificate_requested: boolean;
  certificate_present: boolean;
  certificate_expires_at: string | null;
  detail: string;
};

export function WebSettingsPageClient() {
  const { token } = useAuth();
  const { locale } = useLocale();
  const [webSettings, setWebSettings] = useState<WebSettings | null>(null);
  const [webStatus, setWebStatus] = useState<WebStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [checkingWebStatus, setCheckingWebStatus] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const copy = locale === "ru"
    ? {
        eyebrow: "Веб-интерфейс",
        title: "Web / HTTPS",
        subtitle: "Безопасный foundation для публикации панели: домен, email, режим HTTP/HTTPS, диагностика и preview nginx-конфига.",
        noData: "Настройки веб-интерфейса пока не загружены.",
        save: "Сохранить настройки",
        applyHttp: "Применить web-настройки",
        applyHttps: "Применить и выпустить сертификат",
        saveSuccess: "Настройки веб-интерфейса сохранены.",
        applySuccess: "Настройки веб-интерфейса применены.",
        webDomain: "Публичный домен",
        webEmail: "Email для Let's Encrypt",
        webMode: "Режим панели",
        webModeHttp: "HTTP",
        webModeHttps: "HTTPS",
        webCheck: "Проверить web-статус",
        webDns: "DNS",
        webResolvedIps: "IP адреса",
        webPort80: "Порт 80",
        webPort443: "Порт 443",
        webCertificate: "Сертификат",
        webCertificateExpires: "Истекает",
        webConfigPreview: "Preview nginx config",
        webManualHint: "Кнопка применения записывает live nginx-конфиг, перезагружает nginx и в HTTPS-режиме пытается выпустить или продлить сертификат через Let's Encrypt. Для выпуска сертификата домен уже должен смотреть на этот VPS, а порты 80 и 443 должны быть доступны снаружи.",
        webStatusReady: "Готово",
        webStatusMissing: "Не готово",
        webStatusUnknown: "Нет данных",
        webRefreshSuccess: "Web-статус обновлён.",
      }
    : {
        eyebrow: "Web UI",
        title: "Web / HTTPS",
        subtitle: "Safe foundation for publishing the panel: domain, email, HTTP/HTTPS mode, diagnostics and nginx config preview.",
        noData: "Web interface settings have not been loaded yet.",
        save: "Save settings",
        applyHttp: "Apply web settings",
        applyHttps: "Apply and issue certificate",
        saveSuccess: "Web interface settings saved.",
        applySuccess: "Web interface settings applied.",
        webDomain: "Public domain",
        webEmail: "Let's Encrypt email",
        webMode: "Panel mode",
        webModeHttp: "HTTP",
        webModeHttps: "HTTPS",
        webCheck: "Check web status",
        webDns: "DNS",
        webResolvedIps: "Resolved IPs",
        webPort80: "Port 80",
        webPort443: "Port 443",
        webCertificate: "Certificate",
        webCertificateExpires: "Expires",
        webConfigPreview: "nginx config preview",
        webManualHint: "The apply action writes the live nginx config, reloads nginx, and in HTTPS mode attempts to issue or renew the Let's Encrypt certificate. The domain must already point to this VPS and ports 80 and 443 must be reachable from the internet.",
        webStatusReady: "Ready",
        webStatusMissing: "Missing",
        webStatusUnknown: "No data",
        webRefreshSuccess: "Web status refreshed.",
      };

  useEffect(() => {
    async function loadSettings() {
      if (!token) {
        return;
      }
      try {
        const nextWebSettings = await apiRequest<WebSettings>("/settings/web", { token });
        const nextWebStatus = await apiRequest<WebStatus>("/settings/web/status", { token });
        setWebSettings(nextWebSettings);
        setWebStatus(nextWebStatus);
        setError(null);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Failed to load web settings");
      }
    }

    void loadSettings();
  }, [token]);

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !webSettings) {
      return;
    }
    setSaving(true);
    setInfo(null);
    setError(null);
    try {
      const updatedWebSettings = await apiRequest<WebSettings>("/settings/web", {
        method: "PATCH",
        token,
        body: {
          public_domain: webSettings.public_domain,
          admin_email: webSettings.admin_email,
          web_mode: webSettings.web_mode,
        },
      });
      const refreshedWebStatus = await apiRequest<WebStatus>("/settings/web/status", { token });
      setWebSettings(updatedWebSettings);
      setWebStatus(refreshedWebStatus);
      setInfo(copy.saveSuccess);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save web settings");
    } finally {
      setSaving(false);
    }
  }

  async function refreshWebStatus() {
    if (!token) {
      return;
    }
    setCheckingWebStatus(true);
    setError(null);
    setInfo(null);
    try {
      const nextWebStatus = await apiRequest<WebStatus>("/settings/web/status", { token });
      setWebStatus(nextWebStatus);
      setInfo(copy.webRefreshSuccess);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to refresh web status");
    } finally {
      setCheckingWebStatus(false);
    }
  }

  async function applyWebSettings() {
    if (!token || !webSettings) {
      return;
    }
    setApplying(true);
    setError(null);
    setInfo(null);
    try {
      const result = await apiRequest<WebApplyResult>("/settings/web/apply", {
        method: "POST",
        token,
        body: {
          public_domain: webSettings.public_domain,
          admin_email: webSettings.admin_email,
          web_mode: webSettings.web_mode,
        },
      });
      const updatedWebSettings = await apiRequest<WebSettings>("/settings/web", { token });
      const refreshedWebStatus = await apiRequest<WebStatus>("/settings/web/status", { token });
      setWebSettings(updatedWebSettings);
      setWebStatus(refreshedWebStatus);
      setInfo(result.detail || copy.applySuccess);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to apply web settings");
    } finally {
      setApplying(false);
    }
  }

  function webStatusLabel(flag: boolean | null | undefined): string {
    if (flag === true) {
      return copy.webStatusReady;
    }
    if (flag === false) {
      return copy.webStatusMissing;
    }
    return copy.webStatusUnknown;
  }

  return (
    <ProtectedApp>
      <div className="page-header">
        <div>
          <span className="eyebrow">{copy.eyebrow}</span>
          <h2>{copy.title}</h2>
          <p>{copy.subtitle}</p>
        </div>
      </div>
      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="info-box">{info}</div> : null}
      {!webSettings ? (
        <div className="empty-state">{copy.noData}</div>
      ) : (
        <form className="settings-form" onSubmit={saveSettings}>
          <section className="panel-card settings-module">
            <div className="settings-module-head">
              <div>
                <span className="eyebrow">{copy.title}</span>
                <h3>{copy.title}</h3>
                <p>{copy.subtitle}</p>
              </div>
              <div className="settings-module-actions">
                <span className="settings-status-badge">
                  {webStatus?.web_mode?.toUpperCase() ?? webSettings.web_mode.toUpperCase()}
                </span>
                <button
                  type="button"
                  className="primary-button"
                  disabled={saving || applying}
                  onClick={() => void applyWebSettings()}
                >
                  {applying ? "..." : (webSettings.web_mode === "https" ? copy.applyHttps : copy.applyHttp)}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={checkingWebStatus || applying}
                  onClick={() => void refreshWebStatus()}
                >
                  {checkingWebStatus ? "..." : copy.webCheck}
                </button>
              </div>
            </div>
            <div className="form-grid compact-form-grid">
              <label className="field">
                <span>{copy.webDomain}</span>
                <input
                  value={webSettings.public_domain ?? ""}
                  onChange={(event) => setWebSettings({ ...webSettings, public_domain: event.target.value })}
                />
              </label>
              <label className="field">
                <span>{copy.webEmail}</span>
                <input
                  value={webSettings.admin_email ?? ""}
                  onChange={(event) => setWebSettings({ ...webSettings, admin_email: event.target.value })}
                />
              </label>
              <label className="field">
                <span>{copy.webMode}</span>
                <select
                  value={webSettings.web_mode}
                  onChange={(event) => setWebSettings({ ...webSettings, web_mode: event.target.value })}
                >
                  <option value="http">{copy.webModeHttp}</option>
                  <option value="https">{copy.webModeHttps}</option>
                </select>
              </label>
            </div>
            <div className="settings-web-status-grid">
              <div className="settings-web-status-item">
                <span>{copy.webDns}</span>
                <strong>{webStatusLabel(webStatus?.dns_ok)}</strong>
              </div>
              <div className="settings-web-status-item">
                <span>{copy.webPort80}</span>
                <strong>{webStatusLabel(webStatus?.port_80_open)}</strong>
              </div>
              <div className="settings-web-status-item">
                <span>{copy.webPort443}</span>
                <strong>{webStatusLabel(webStatus?.port_443_open)}</strong>
              </div>
              <div className="settings-web-status-item">
                <span>{copy.webCertificate}</span>
                <strong>{webStatusLabel(webStatus?.certificate_present)}</strong>
              </div>
            </div>
            {webStatus?.resolved_ips?.length ? (
              <div className="info-box">
                <strong>{copy.webResolvedIps}:</strong> {webStatus.resolved_ips.join(", ")}
              </div>
            ) : null}
            {webStatus?.certificate_expires_at ? (
              <div className="info-box">
                <strong>{copy.webCertificateExpires}:</strong> {new Date(webStatus.certificate_expires_at).toLocaleString(locale === "ru" ? "ru-RU" : "en-US")}
              </div>
            ) : null}
            {webStatus?.detail ? <div className="info-box">{webStatus.detail}</div> : null}
            <p className="settings-module-note">{copy.webManualHint}</p>
            <div className="preview-box">
              <span className="eyebrow">{copy.webConfigPreview}</span>
              <pre className="config-preview">{webSettings.generated_nginx_config}</pre>
            </div>
          </section>

          <div className="panel-card settings-submit-row">
            <button type="submit" className="primary-button" disabled={saving}>
              {copy.save}
            </button>
          </div>
        </form>
      )}
    </ProtectedApp>
  );
}
