"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "./api";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";
import { ProtectedApp } from "./protected-app";

type DeliverySettings = {
  delivery_email_enabled: boolean;
  delivery_telegram_enabled: boolean;
  admin_email_notifications_enabled: boolean;
  admin_telegram_notifications_enabled: boolean;
  notification_level: string;
  smtp_host: string | null;
  smtp_port: number;
  smtp_username: string | null;
  smtp_password_configured: boolean;
  smtp_from_email: string | null;
  smtp_from_name: string | null;
  smtp_use_tls: boolean;
  telegram_bot_token_configured: boolean;
  telegram_admin_chat_id: string | null;
  admin_notification_email: string | null;
};

type BackupSettings = {
  auto_backup_enabled: boolean;
  auto_backup_hour_utc: number;
  backup_retention_days: number;
  backup_storage_path: string;
};

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

type DeliveryTestResult = {
  channel: string;
  status: string;
  detail: string;
};

type TestState = {
  kind: "success" | "error";
  text: string;
} | null;

const NOTIFICATION_LEVEL_ALIASES: Record<string, string> = {
  delivery_only: "important_only",
  client_lifecycle: "access_changes",
  policy_alerts: "policy_and_expiry",
  system_alerts: "full_monitoring",
};

function normalizeNotificationLevel(level: string | null | undefined): string {
  const raw = (level ?? "").trim();
  if (!raw) {
    return "important_only";
  }
  return NOTIFICATION_LEVEL_ALIASES[raw] ?? raw;
}

export function SettingsPageClient() {
  const { token } = useAuth();
  const { locale } = useLocale();
  const [settings, setSettings] = useState<DeliverySettings | null>(null);
  const [backupSettings, setBackupSettings] = useState<BackupSettings | null>(null);
  const [webSettings, setWebSettings] = useState<WebSettings | null>(null);
  const [webStatus, setWebStatus] = useState<WebStatus | null>(null);
  const [smtpPassword, setSmtpPassword] = useState("");
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [checkingWebStatus, setCheckingWebStatus] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);
  const [testingTelegram, setTestingTelegram] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [emailTestState, setEmailTestState] = useState<TestState>(null);
  const [telegramTestState, setTelegramTestState] = useState<TestState>(null);

  const copy = locale === "ru"
    ? {
        eyebrow: "Настройки",
        title: "Настройки доставки и уведомлений.",
        noData: "Настройки пока не загружены.",
        save: "Сохранить настройки",
        saveSuccess: "Настройки сохранены.",
        on: "Включено",
        off: "Выключено",
        configured: "Настроено",
        notConfigured: "Не настроено",
        notificationsTitle: "Уведомления",
        notificationsSubtitle: "Глобальные правила уведомлений панели и администраторов.",
        emailTitle: "Почта",
        emailSubtitle: "SMTP-параметры и тестовая отправка на административный email.",
        telegramTitle: "Telegram",
        telegramSubtitle: "Настройки бота и тестовая отправка в административный чат.",
        level: "Уровень уведомлений",
        deliveryEmail: "Доставка конфигов по почте",
        deliveryTelegram: "Доставка конфигов в Telegram",
        adminEmailNotifications: "Уведомления администратору по почте",
        adminTelegramNotifications: "Уведомления администратору в Telegram",
        smtpHost: "SMTP хост",
        smtpPort: "SMTP порт",
        smtpUsername: "SMTP пользователь",
        smtpPassword: "SMTP пароль",
        smtpPasswordConfigured: "SMTP пароль сохранён",
        fromEmail: "Email отправителя",
        fromName: "Имя отправителя",
        smtpTls: "SMTP TLS",
        adminEmail: "Административные email",
        testEmail: "Проверить почту",
        emailHint: "Проверка уйдёт на все административные email из настроек. Можно указывать по одному адресу на строку или через запятую.",
        telegramBotToken: "Токен Telegram бота",
        telegramBotConfigured: "Токен Telegram сохранён",
        telegramAdminChatId: "Telegram admin chat id",
        testTelegram: "Проверить Telegram",
        telegramHint: "Проверка уйдёт в административный Telegram chat id.",
        autoBackups: "Автобэкапы панели",
        backupHourUtc: "Час запуска (UTC)",
        retentionDays: "Хранить архивы, дней",
        storagePath: "Путь хранения архивов",
        storagePathHint: "Путь задаётся через env BACKUP_STORAGE_PATH и меняется вне панели.",
        webTitle: "Web / HTTPS",
        webSubtitle: "Безопасный foundation для публикации панели: домен, email, режим HTTP/HTTPS, диагностика и preview nginx-конфига.",
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
        webManualHint: "Панель пока только хранит параметры, показывает диагностику и генерирует preview. Выпуск сертификата, reload nginx и certbot запускаются вручную одной командой вне UI.",
        webStatusReady: "Готово",
        webStatusMissing: "Не готово",
        webStatusUnknown: "Нет данных",
        webRefreshSuccess: "Web-статус обновлён.",
        optionDisabled: "Отключено",
        optionImportantOnly: "Только важное",
        optionAccessChanges: "Доступ и изменения",
        optionPolicyAndExpiry: "Политики и сроки",
        optionFullMonitoring: "Полный мониторинг",
        levelHelpDisabled: "Автоматические уведомления администратору отключены. Ручная доставка конфигов остаётся отдельной функцией.",
        levelHelpImportantOnly: "Только критичные события: недоступность сервера, ошибки deploy/sync, сбой backup, остановка по лимиту или истечение доступа.",
        levelHelpAccessChanges: "Всё из уровня «Только важное» плюс создание, перевыпуск, архивирование, ручное включение и выключение клиентов, а также отправка конфигов.",
        levelHelpPolicyAndExpiry: "Всё из уровня «Доступ и изменения» плюс quiet hours, предупреждения по срокам, предупреждения и срабатывания лимитов.",
        levelHelpFullMonitoring: "Полный поток: системные события панели, backup success/failure, ошибки интеграций, деградация и восстановление серверов.",
      }
    : {
        eyebrow: "Settings",
        title: "Delivery and notification settings.",
        noData: "Settings have not been loaded yet.",
        save: "Save settings",
        saveSuccess: "Settings saved.",
        on: "On",
        off: "Off",
        configured: "Configured",
        notConfigured: "Not configured",
        notificationsTitle: "Notifications",
        notificationsSubtitle: "Global notification rules for the panel and administrators.",
        emailTitle: "Email",
        emailSubtitle: "SMTP parameters and a test message sent to the admin email.",
        telegramTitle: "Telegram",
        telegramSubtitle: "Bot settings and a test message sent to the admin chat.",
        level: "Notification level",
        deliveryEmail: "Config delivery by email",
        deliveryTelegram: "Config delivery by Telegram",
        adminEmailNotifications: "Admin email notifications",
        adminTelegramNotifications: "Admin Telegram notifications",
        smtpHost: "SMTP host",
        smtpPort: "SMTP port",
        smtpUsername: "SMTP username",
        smtpPassword: "SMTP password",
        smtpPasswordConfigured: "SMTP password is stored",
        fromEmail: "From email",
        fromName: "From name",
        smtpTls: "SMTP TLS",
        adminEmail: "Admin notification emails",
        testEmail: "Test email",
        emailHint: "The test message will be sent to all admin emails from this field. You can use one address per line or comma-separated values.",
        telegramBotToken: "Telegram bot token",
        telegramBotConfigured: "Telegram bot token is stored",
        telegramAdminChatId: "Telegram admin chat id",
        testTelegram: "Test Telegram",
        telegramHint: "The test message will be sent to the admin Telegram chat id.",
        autoBackups: "Automatic panel backups",
        backupHourUtc: "Run hour (UTC)",
        retentionDays: "Keep archives, days",
        storagePath: "Archive storage path",
        storagePathHint: "This path is configured via BACKUP_STORAGE_PATH env and is read-only in the panel.",
        webTitle: "Web / HTTPS",
        webSubtitle: "Safe foundation for publishing the panel: domain, email, HTTP/HTTPS mode, diagnostics and nginx config preview.",
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
        webManualHint: "The panel currently stores parameters, shows diagnostics and generates a preview only. Certificate issuance, nginx reload and certbot are still run manually outside the UI.",
        webStatusReady: "Ready",
        webStatusMissing: "Missing",
        webStatusUnknown: "No data",
        webRefreshSuccess: "Web status refreshed.",
        optionDisabled: "Disabled",
        optionImportantOnly: "Important only",
        optionAccessChanges: "Access and changes",
        optionPolicyAndExpiry: "Policies and expiry",
        optionFullMonitoring: "Full monitoring",
        levelHelpDisabled: "Automatic admin notifications are disabled. Manual config delivery remains a separate feature.",
        levelHelpImportantOnly: "Only critical events: server unavailable, deploy/sync failures, backup failures, traffic-limit disable or client expiration.",
        levelHelpAccessChanges: "Everything from “Important only”, plus client creation, reissue, archiving, manual enable/disable and config deliveries.",
        levelHelpPolicyAndExpiry: "Everything from “Access and changes”, plus quiet hours, expiry warnings, limit warnings and policy-triggered state changes.",
        levelHelpFullMonitoring: "Full stream: panel system events, backup success/failure, delivery integration failures, and server degradation/restoration.",
      };

  function notificationLevelDescription(level: string): string {
    switch (normalizeNotificationLevel(level)) {
      case "disabled":
        return copy.levelHelpDisabled;
      case "access_changes":
        return copy.levelHelpAccessChanges;
      case "policy_and_expiry":
        return copy.levelHelpPolicyAndExpiry;
      case "full_monitoring":
        return copy.levelHelpFullMonitoring;
      case "important_only":
      default:
        return copy.levelHelpImportantOnly;
    }
  }

  async function loadSettings() {
    if (!token) {
      return;
    }
    try {
      const nextSettings = await apiRequest<DeliverySettings>("/settings/delivery", { token });
      const nextBackupSettings = await apiRequest<BackupSettings>("/settings/backups", { token });
      const nextWebSettings = await apiRequest<WebSettings>("/settings/web", { token });
      const nextWebStatus = await apiRequest<WebStatus>("/settings/web/status", { token });
      setSettings({ ...nextSettings, notification_level: normalizeNotificationLevel(nextSettings.notification_level) });
      setBackupSettings(nextBackupSettings);
      setWebSettings(nextWebSettings);
      setWebStatus(nextWebStatus);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load settings");
    }
  }

  useEffect(() => {
    void loadSettings();
  }, [token]);

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !settings || !backupSettings || !webSettings) {
      return;
    }
    setSaving(true);
    setInfo(null);
    setError(null);
    try {
      const updated = await apiRequest<DeliverySettings>("/settings/delivery", {
        method: "PATCH",
        token,
        body: {
          ...settings,
          notification_level: normalizeNotificationLevel(settings.notification_level),
          smtp_password: smtpPassword.trim() || null,
          telegram_bot_token: telegramBotToken.trim() || null,
        },
      });
      const updatedBackupSettings = await apiRequest<BackupSettings>("/settings/backups", {
        method: "PATCH",
        token,
        body: backupSettings,
      });
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
      setSettings({ ...updated, notification_level: normalizeNotificationLevel(updated.notification_level) });
      setBackupSettings(updatedBackupSettings);
      setWebSettings(updatedWebSettings);
      setWebStatus(refreshedWebStatus);
      setSmtpPassword("");
      setTelegramBotToken("");
      setInfo(copy.saveSuccess);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  async function testChannel(path: string, channel: "email" | "telegram") {
    if (!token) {
      return;
    }
    const setLoading = channel === "email" ? setTestingEmail : setTestingTelegram;
    const setState = channel === "email" ? setEmailTestState : setTelegramTestState;
    setLoading(true);
    setState(null);
    try {
      const result = await apiRequest<DeliveryTestResult>(path, {
        method: "POST",
        token,
      });
      setState({ kind: "success", text: result.detail });
    } catch (nextError) {
      setState({
        kind: "error",
        text: nextError instanceof Error ? nextError.message : "Test failed",
      });
    } finally {
      setLoading(false);
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
        </div>
      </div>
      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="info-box">{info}</div> : null}
      {!settings || !backupSettings || !webSettings ? (
        <div className="empty-state">{copy.noData}</div>
      ) : (
        <form className="settings-form" onSubmit={saveSettings}>
          <section className="panel-card settings-module">
            <div className="settings-module-head">
              <div>
                <span className="eyebrow">{copy.webTitle}</span>
                <h3>{copy.webTitle}</h3>
                <p>{copy.webSubtitle}</p>
              </div>
              <div className="settings-module-actions">
                <span className="settings-status-badge">
                  {webStatus?.web_mode?.toUpperCase() ?? webSettings.web_mode.toUpperCase()}
                </span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={checkingWebStatus}
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
                <span className="eyebrow">{copy.notificationsTitle}</span>
                <h3>{copy.notificationsTitle}</h3>
                <p>{copy.notificationsSubtitle}</p>
              </div>
            </div>
            <div className="form-grid compact-form-grid">
              <label className="field">
                <span>{copy.level}</span>
                <select value={normalizeNotificationLevel(settings.notification_level)} onChange={(event) => setSettings({ ...settings, notification_level: event.target.value })}>
                  <option value="disabled">{copy.optionDisabled}</option>
                  <option value="important_only">{copy.optionImportantOnly}</option>
                  <option value="access_changes">{copy.optionAccessChanges}</option>
                  <option value="policy_and_expiry">{copy.optionPolicyAndExpiry}</option>
                  <option value="full_monitoring">{copy.optionFullMonitoring}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.deliveryEmail}</span>
                <select value={settings.delivery_email_enabled ? "on" : "off"} onChange={(event) => setSettings({ ...settings, delivery_email_enabled: event.target.value === "on" })}>
                  <option value="on">{copy.on}</option>
                  <option value="off">{copy.off}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.deliveryTelegram}</span>
                <select value={settings.delivery_telegram_enabled ? "on" : "off"} onChange={(event) => setSettings({ ...settings, delivery_telegram_enabled: event.target.value === "on" })}>
                  <option value="on">{copy.on}</option>
                  <option value="off">{copy.off}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.adminEmailNotifications}</span>
                <select value={settings.admin_email_notifications_enabled ? "on" : "off"} onChange={(event) => setSettings({ ...settings, admin_email_notifications_enabled: event.target.value === "on" })}>
                  <option value="on">{copy.on}</option>
                  <option value="off">{copy.off}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.adminTelegramNotifications}</span>
                <select value={settings.admin_telegram_notifications_enabled ? "on" : "off"} onChange={(event) => setSettings({ ...settings, admin_telegram_notifications_enabled: event.target.value === "on" })}>
                  <option value="on">{copy.on}</option>
                  <option value="off">{copy.off}</option>
                </select>
              </label>
            </div>
            <div className="settings-level-help">
              {notificationLevelDescription(settings.notification_level)}
            </div>
          </section>

          <section className="panel-card settings-module">
            <div className="settings-module-head">
              <div>
                <span className="eyebrow">{copy.emailTitle}</span>
                <h3>{copy.emailTitle}</h3>
                <p>{copy.emailSubtitle}</p>
              </div>
              <div className="settings-module-actions">
                <span className="settings-status-badge">
                  {settings.smtp_password_configured ? copy.configured : copy.notConfigured}
                </span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={testingEmail}
                  onClick={() => void testChannel("/settings/delivery/test-email", "email")}
                >
                  {testingEmail ? "..." : copy.testEmail}
                </button>
              </div>
            </div>
            <div className="form-grid compact-form-grid">
              <label className="field">
                <span>{copy.smtpHost}</span>
                <input value={settings.smtp_host ?? ""} onChange={(event) => setSettings({ ...settings, smtp_host: event.target.value })} />
              </label>
              <label className="field">
                <span>{copy.smtpPort}</span>
                <input type="number" value={settings.smtp_port} onChange={(event) => setSettings({ ...settings, smtp_port: Number(event.target.value) })} />
              </label>
              <label className="field">
                <span>{copy.smtpUsername}</span>
                <input value={settings.smtp_username ?? ""} onChange={(event) => setSettings({ ...settings, smtp_username: event.target.value })} />
              </label>
              <label className="field">
                <span>
                  {copy.smtpPassword}
                  {settings.smtp_password_configured ? ` • ${copy.smtpPasswordConfigured}` : ""}
                </span>
                <input type="password" value={smtpPassword} onChange={(event) => setSmtpPassword(event.target.value)} />
              </label>
              <label className="field">
                <span>{copy.fromEmail}</span>
                <input value={settings.smtp_from_email ?? ""} onChange={(event) => setSettings({ ...settings, smtp_from_email: event.target.value })} />
              </label>
              <label className="field">
                <span>{copy.fromName}</span>
                <input value={settings.smtp_from_name ?? ""} onChange={(event) => setSettings({ ...settings, smtp_from_name: event.target.value })} />
              </label>
              <label className="field">
                <span>{copy.smtpTls}</span>
                <select value={settings.smtp_use_tls ? "on" : "off"} onChange={(event) => setSettings({ ...settings, smtp_use_tls: event.target.value === "on" })}>
                  <option value="on">{copy.on}</option>
                  <option value="off">{copy.off}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.adminEmail}</span>
                <textarea
                  className="textarea-input"
                  rows={3}
                  value={settings.admin_notification_email ?? ""}
                  onChange={(event) => setSettings({ ...settings, admin_notification_email: event.target.value })}
                />
              </label>
            </div>
            <p className="settings-module-note">{copy.emailHint}</p>
            {emailTestState ? (
              <div className={emailTestState.kind === "success" ? "info-box" : "error-box"}>
                {emailTestState.text}
              </div>
            ) : null}
          </section>

          <section className="panel-card settings-module">
            <div className="settings-module-head">
              <div>
                <span className="eyebrow">{copy.telegramTitle}</span>
                <h3>{copy.telegramTitle}</h3>
                <p>{copy.telegramSubtitle}</p>
              </div>
              <div className="settings-module-actions">
                <span className="settings-status-badge">
                  {settings.telegram_bot_token_configured ? copy.configured : copy.notConfigured}
                </span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={testingTelegram}
                  onClick={() => void testChannel("/settings/delivery/test-telegram", "telegram")}
                >
                  {testingTelegram ? "..." : copy.testTelegram}
                </button>
              </div>
            </div>
            <div className="form-grid compact-form-grid">
              <label className="field">
                <span>
                  {copy.telegramBotToken}
                  {settings.telegram_bot_token_configured ? ` • ${copy.telegramBotConfigured}` : ""}
                </span>
                <input type="password" value={telegramBotToken} onChange={(event) => setTelegramBotToken(event.target.value)} />
              </label>
              <label className="field">
                <span>{copy.telegramAdminChatId}</span>
                <input value={settings.telegram_admin_chat_id ?? ""} onChange={(event) => setSettings({ ...settings, telegram_admin_chat_id: event.target.value })} />
              </label>
            </div>
            <p className="settings-module-note">{copy.telegramHint}</p>
            {telegramTestState ? (
              <div className={telegramTestState.kind === "success" ? "info-box" : "error-box"}>
                {telegramTestState.text}
              </div>
            ) : null}
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
