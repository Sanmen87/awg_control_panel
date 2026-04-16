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
  external_api_enabled: boolean;
  external_api_token_configured: boolean;
  external_api_token_prefix: string | null;
  external_api_token_scopes: string[];
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

type WebExternalApiTokenResult = {
  token: string;
  token_prefix: string;
  scopes: string[];
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
  const [generatingApiToken, setGeneratingApiToken] = useState(false);
  const [generatedApiToken, setGeneratedApiToken] = useState<WebExternalApiTokenResult | null>(null);
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
        externalApiTitle: "Внешний API",
        externalApiSubtitle: "Включи API, сгенерируй токен и передай его внешней системе. Токен показывается только один раз.",
        externalApiEnabled: "Включить внешний API",
        externalApiToken: "API token",
        externalApiTokenConfigured: "Токен выпущен",
        externalApiTokenMissing: "Токен ещё не выпущен",
        externalApiTokenPrefix: "Префикс токена",
        externalApiScopes: "Scopes",
        externalApiGenerate: "Сгенерировать / перевыпустить токен",
        externalApiGenerated: "Токен сгенерирован. Сохрани его сейчас, потом он не будет показан.",
        externalApiUsage: "Как использовать",
        externalApiDisabledHint: "Если внешний API выключен, все запросы к /api/v1/external/* будут получать 403 даже с правильным токеном.",
        externalApiCopy: "Скопировать token",
        externalApiCopied: "Токен скопирован.",
        externalApiCopyFailed: "Не удалось скопировать токен.",
        externalApiTurnOn: "Включить API",
        externalApiTurnOff: "Выключить API",
        toggleOn: "Включено",
        toggleOff: "Выключено",
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
        externalApiTitle: "External API",
        externalApiSubtitle: "Enable the API, generate a token, and pass it to the external system. The token is shown only once.",
        externalApiEnabled: "Enable external API",
        externalApiToken: "API token",
        externalApiTokenConfigured: "Token issued",
        externalApiTokenMissing: "Token has not been issued yet",
        externalApiTokenPrefix: "Token prefix",
        externalApiScopes: "Scopes",
        externalApiGenerate: "Generate / rotate token",
        externalApiGenerated: "Token generated. Store it now; it will not be shown again.",
        externalApiUsage: "How to use",
        externalApiDisabledHint: "If external API is disabled, all /api/v1/external/* requests return 403 even with a valid token.",
        externalApiCopy: "Copy token",
        externalApiCopied: "Token copied.",
        externalApiCopyFailed: "Failed to copy token.",
        externalApiTurnOn: "Enable API",
        externalApiTurnOff: "Disable API",
        toggleOn: "On",
        toggleOff: "Off",
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
          external_api_enabled: webSettings.external_api_enabled,
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
          external_api_enabled: webSettings.external_api_enabled,
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

  async function generateExternalApiToken() {
    if (!token) {
      return;
    }
    setGeneratingApiToken(true);
    setError(null);
    setInfo(null);
    try {
      const result = await apiRequest<WebExternalApiTokenResult>("/settings/web/external-api-token", {
        method: "POST",
        token,
      });
      const updatedWebSettings = await apiRequest<WebSettings>("/settings/web", { token });
      setGeneratedApiToken(result);
      setWebSettings(updatedWebSettings);
      setInfo(copy.externalApiGenerated);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to generate API token");
    } finally {
      setGeneratingApiToken(false);
    }
  }

  async function copyGeneratedApiToken() {
    if (!generatedApiToken?.token) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedApiToken.token);
      setInfo(copy.externalApiCopied);
    } catch {
      setError(copy.externalApiCopyFailed);
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

          <section className="panel-card settings-module">
            <div className="settings-module-head">
              <div>
                <span className="eyebrow">{copy.externalApiTitle}</span>
                <h3>{copy.externalApiTitle}</h3>
                <p>{copy.externalApiSubtitle}</p>
              </div>
              <div className="settings-module-actions">
                <button
                  type="button"
                  className={webSettings.external_api_enabled ? "switch-button switch-button-on switch-button-inline" : "switch-button switch-button-inline"}
                  aria-pressed={webSettings.external_api_enabled}
                  onClick={() => setWebSettings({ ...webSettings, external_api_enabled: !webSettings.external_api_enabled })}
                >
                  <span className="switch-button-knob" />
                  <span>{webSettings.external_api_enabled ? copy.externalApiTurnOff : copy.externalApiTurnOn}</span>
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={generatingApiToken}
                  onClick={() => void generateExternalApiToken()}
                >
                  {generatingApiToken ? "..." : copy.externalApiGenerate}
                </button>
              </div>
            </div>
            <div className="settings-web-status-grid">
              <div className="settings-web-status-item">
                <span>{copy.externalApiToken}</span>
                <strong>{webSettings.external_api_token_configured ? copy.externalApiTokenConfigured : copy.externalApiTokenMissing}</strong>
              </div>
              <div className="settings-web-status-item">
                <span>{copy.externalApiTokenPrefix}</span>
                <strong>{webSettings.external_api_token_prefix ?? "-"}</strong>
              </div>
              <div className="settings-web-status-item">
                <span>{copy.externalApiScopes}</span>
                <strong>{webSettings.external_api_token_scopes.length ? webSettings.external_api_token_scopes.length : "-"}</strong>
              </div>
            </div>
            <p className="settings-module-note">{copy.externalApiDisabledHint}</p>
            {webSettings.external_api_token_scopes.length ? (
              <div className="info-box">
                <strong>{copy.externalApiScopes}:</strong> {webSettings.external_api_token_scopes.join(", ")}
              </div>
            ) : null}
            {generatedApiToken ? (
              <div className="preview-box">
                <span className="eyebrow">{copy.externalApiToken}</span>
                <pre className="config-preview">{generatedApiToken.token}</pre>
                <button type="button" className="secondary-button" onClick={() => void copyGeneratedApiToken()}>
                  {copy.externalApiCopy}
                </button>
              </div>
            ) : null}
            <div className="preview-box">
              <span className="eyebrow">{copy.externalApiUsage}</span>
              <pre className="config-preview">{`curl -H "Authorization: Bearer <TOKEN>" ${webSettings.public_domain ? `https://${webSettings.public_domain}` : "https://panel.example.com"}/api/v1/external/client-targets
curl -H "Authorization: Bearer <TOKEN>" ${webSettings.public_domain ? `https://${webSettings.public_domain}` : "https://panel.example.com"}/api/v1/external/clients
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \\
  -d '{"name":"client-001"}' \\
  ${webSettings.public_domain ? `https://${webSettings.public_domain}` : "https://panel.example.com"}/api/v1/external/topologies/2/clients
curl -X POST -H "Authorization: Bearer <TOKEN>" \\
  ${webSettings.public_domain ? `https://${webSettings.public_domain}` : "https://panel.example.com"}/api/v1/external/clients/123/suspend`}</pre>
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
