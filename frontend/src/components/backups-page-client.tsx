"use client";

import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type BackupJob = {
  id: number;
  backup_type: string;
  server_id: number | null;
  status: string;
  storage_path: string | null;
  result_message: string | null;
  manifest_server_name: string | null;
  manifest_server_host: string | null;
  manifest_install_method: string | null;
  created_at: string;
  updated_at: string;
};

type Server = {
  id: number;
  name: string;
  host: string;
  awg_detected: boolean;
  ready_for_topology: boolean;
};

type Job = {
  id: number;
  job_type: string;
  status: string;
  server_id: number | null;
  result_message: string | null;
  created_at: string;
};

type BackupSettings = {
  auto_backup_enabled: boolean;
  auto_backup_hour_utc: number;
  backup_retention_days: number;
  backup_storage_path: string;
};

type BackupPreviewServer = {
  server_id: number;
  name: string | null;
  host: string | null;
  install_method: string | null;
  runtime_flavor: string | null;
  live_interface_name: string | null;
  live_config_path: string | null;
  clients_table_path: string | null;
  has_clients_table: boolean;
};

type BackupPreview = {
  backup_type: string;
  created_at: string | null;
  panel_project_name: string | null;
  has_panel_dump: boolean;
  servers: BackupPreviewServer[];
};

export function BackupsPageClient() {
  const { token } = useAuth();
  const { locale } = useLocale();
  const [backups, setBackups] = useState<BackupJob[]>([]);
  const [servers, setServers] = useState<Server[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [backupSettings, setBackupSettings] = useState<BackupSettings | null>(null);
  const [restoreTargetByBackup, setRestoreTargetByBackup] = useState<Record<number, string>>({});
  const [previewByBackup, setPreviewByBackup] = useState<Record<number, BackupPreview | null>>({});
  const [bundleTargetByBackup, setBundleTargetByBackup] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showOlderBackups, setShowOlderBackups] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  const copy = locale === "ru"
    ? {
        eyebrow: "Бэкапы",
        title: "Резервные копии и восстановление серверов.",
        createTitle: "Новый backup",
        createFullBundle: "Снять полный бэкап",
        creatingFull: "Создаю полный bundle...",
        uploadTitle: "Загрузить bundle",
        uploadHint: "Сюда загружается recovery bundle для ручного preview и восстановления через панель.",
        backupSettingsTitle: "Автобэкапы и очистка",
        backupSettingsHint: "Эти настройки управляют автоматическим созданием panel backup и удалением старых архивов.",
        autoBackups: "Автобэкапы панели",
        backupHourUtc: "Час запуска (UTC)",
        retentionDays: "Хранить архивы, дней",
        saveBackupSettings: "Сохранить политику бэкапов",
        savingBackupSettings: "Сохраняю политику...",
        restoreHint: "Перед восстановлением сервер нужно сначала добавить в панель и проверить SSH-доступ.",
        backupServer: "Сервер",
        chooseFile: "Файл архива",
        uploadBackup: "Загрузить bundle",
        uploading: "Загружаю архив...",
        download: "Скачать архив",
        delete: "Удалить из панели",
        deleting: "Удаляю...",
        restoreServer: "Восстановить на сервер",
        restorePanel: "Восстановить панель",
        preview: "Показать состав",
        hidePreview: "Скрыть состав",
        previewTitle: "Состав bundle",
        previewPanelOnly: "В этом архиве есть только дамп панели. Через UI сейчас можно восстановить только панель.",
        previewNoServers: "В этом bundle нет серверных конфигов для ручного восстановления.",
        previewWithServers: "В архиве есть дамп панели и серверные конфиги. Ниже можно выбрать, что именно восстанавливать.",
        bundledServer: "Сервер из bundle",
        restoreBundleServer: "Восстановить сервер из bundle",
        restoringBundleServer: "Запускаю restore сервера...",
        restore: "Восстановить",
        restoring: "Запускаю restore...",
        empty: "Backup jobs пока не создавались.",
        latestJobs: "Связанные задачи",
        storage: "Архив",
        result: "Результат",
        source: "Источник архива",
        status: "Статус",
        type: "Тип",
        createdAt: "Создано",
        noArchive: "Архив ещё не готов",
        panelRestoreHint: "Полный бэкап включает панель и серверные конфиги в одном bundle.",
        recentBackups: "Последние архивы",
        olderBackups: "Старые архивы",
        showOlderBackups: "Показать старые архивы",
        hideOlderBackups: "Скрыть старые архивы",
        archiveCount: "архивов",
      }
    : {
        eyebrow: "Backups",
        title: "Server backups and restore jobs.",
        createTitle: "New backup",
        createFullBundle: "Create full backup",
        creatingFull: "Creating full bundle...",
        uploadTitle: "Upload bundle",
        uploadHint: "Upload a recovery bundle here for manual preview and restore through the panel.",
        backupSettingsTitle: "Auto backups and cleanup",
        backupSettingsHint: "These settings control automatic panel backups and cleanup of old archives.",
        autoBackups: "Automatic panel backups",
        backupHourUtc: "Run hour (UTC)",
        retentionDays: "Keep archives, days",
        saveBackupSettings: "Save backup policy",
        savingBackupSettings: "Saving policy...",
        restoreHint: "Before restore, add the target server to the panel first and verify SSH access.",
        backupServer: "Server",
        chooseFile: "Archive file",
        uploadBackup: "Upload bundle",
        uploading: "Uploading archive...",
        download: "Download archive",
        delete: "Delete from panel",
        deleting: "Deleting...",
        restoreServer: "Restore to server",
        restorePanel: "Restore panel",
        preview: "Show contents",
        hidePreview: "Hide contents",
        previewTitle: "Bundle contents",
        previewPanelOnly: "This archive contains only the panel dump. In the UI you can currently restore only the panel from it.",
        previewNoServers: "This bundle does not contain server configs for manual restore.",
        previewWithServers: "This archive contains the panel dump and server configs. Choose what to restore below.",
        bundledServer: "Bundled server",
        restoreBundleServer: "Restore bundled server",
        restoringBundleServer: "Starting server restore...",
        restore: "Restore",
        restoring: "Starting restore...",
        empty: "No backup jobs yet.",
        latestJobs: "Related jobs",
        storage: "Archive",
        result: "Result",
        source: "Archive source",
        status: "Status",
        type: "Type",
        createdAt: "Created",
        noArchive: "Archive is not ready yet",
        panelRestoreHint: "A full backup includes the panel state and server configs in one bundle.",
        recentBackups: "Recent archives",
        olderBackups: "Older archives",
        showOlderBackups: "Show older archives",
        hideOlderBackups: "Hide older archives",
        archiveCount: "archives",
      };

  async function loadData() {
    if (!token) {
      return;
    }
    try {
      const [nextBackups, nextServers, nextJobs, nextBackupSettings] = await Promise.all([
        apiRequest<BackupJob[]>("/backups", { token }),
        apiRequest<Server[]>("/servers", { token }),
        apiRequest<Job[]>("/jobs", { token }),
        apiRequest<BackupSettings>("/settings/backups", { token }),
      ]);
      setBackups(nextBackups);
      setServers(nextServers);
      setJobs(nextJobs);
      setBackupSettings(nextBackupSettings);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load backups");
    }
  }

  useEffect(() => {
    void loadData();
    if (!token) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadData();
    }, 10000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  useEffect(() => {
    setRestoreTargetByBackup((previous) => {
      const next = { ...previous };
      let changed = false;
      for (const backup of backups) {
        if (next[backup.id]) {
          continue;
        }
        const directServer = backup.server_id ? servers.find((server) => server.id === backup.server_id) : null;
        const hostMatch = backup.manifest_server_host
          ? servers.find((server) => server.host === backup.manifest_server_host)
          : null;
        const nameMatch = backup.manifest_server_name
          ? servers.find((server) => server.name === backup.manifest_server_name)
          : null;
        const suggested = directServer ?? hostMatch ?? nameMatch ?? null;
        if (!suggested) {
          continue;
        }
        next[backup.id] = String(suggested.id);
        changed = true;
      }
      return changed ? next : previous;
    });
  }, [backups, servers]);

  const backupableServers = useMemo(
    () => servers.filter((server) => server.awg_detected || server.ready_for_topology),
    [servers]
  );
  const recentBackups = useMemo(() => backups.slice(0, 5), [backups]);
  const olderBackups = useMemo(() => backups.slice(5), [backups]);

  function serverLabel(serverId: number | null) {
    if (!serverId) {
      return "-";
    }
    const server = servers.find((item) => item.id === serverId);
    return server ? `${server.name} (${server.host})` : `#${serverId}`;
  }

  function relatedJob(backupId: number) {
    return jobs.find((job) => job.result_message === `BackupJob:${backupId}` || job.result_message === `RestoreBackupJob:${backupId}`) ?? null;
  }

  function isUploadedBackup(backup: BackupJob) {
    return (backup.result_message ?? "").toLowerCase().includes("uploaded backup archive");
  }

  function backupSourceLabel(backup: BackupJob) {
    if (backup.manifest_server_name && backup.manifest_server_host) {
      return `${backup.manifest_server_name} (${backup.manifest_server_host})`;
    }
    if (backup.manifest_server_host) {
      return backup.manifest_server_host;
    }
    if (backup.manifest_server_name) {
      return backup.manifest_server_name;
    }
    return "-";
  }

  async function createFullBundleBackup() {
    if (!token) {
      return;
    }
    setSaving(true);
    setInfo(null);
    try {
      await apiRequest<BackupJob>("/backups", {
        method: "POST",
        token,
        body: {
          backup_type: "full",
        },
      });
      setInfo(locale === "ru" ? "Полный bundle создан." : "Full bundle backup job created.");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to create full bundle backup");
    } finally {
      setSaving(false);
    }
  }

  async function saveBackupSettings() {
    if (!token || !backupSettings) {
      return;
    }
    setSaving(true);
    setInfo(null);
    try {
      const updated = await apiRequest<BackupSettings>("/settings/backups", {
        method: "PATCH",
        token,
        body: {
          auto_backup_enabled: backupSettings.auto_backup_enabled,
          auto_backup_hour_utc: backupSettings.auto_backup_hour_utc,
          backup_retention_days: backupSettings.backup_retention_days,
        },
      });
      setBackupSettings(updated);
      setInfo(locale === "ru" ? "Политика бэкапов сохранена." : "Backup policy saved.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save backup policy");
    } finally {
      setSaving(false);
    }
  }

  async function togglePreview(backup: BackupJob) {
    if (!token) {
      return;
    }
    if (previewByBackup[backup.id]) {
      setPreviewByBackup((current) => ({ ...current, [backup.id]: null }));
      return;
    }
    try {
      const preview = await apiRequest<BackupPreview>(`/backups/${backup.id}/preview`, { token });
      setPreviewByBackup((current) => ({ ...current, [backup.id]: preview }));
      if (preview.backup_type === "full") {
        setBundleTargetByBackup((current) => {
          const next = { ...current };
          for (const bundledServer of preview.servers) {
            const key = `${backup.id}:${bundledServer.server_id}`;
            if (next[key]) {
              continue;
            }
            const hostMatch = bundledServer.host ? servers.find((server) => server.host === bundledServer.host) : null;
            const nameMatch = bundledServer.name ? servers.find((server) => server.name === bundledServer.name) : null;
            const suggested = hostMatch ?? nameMatch ?? null;
            if (suggested) {
              next[key] = String(suggested.id);
            }
          }
          return next;
        });
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load backup preview");
    }
  }

  async function restoreBackup(backup: BackupJob) {
    if (!token) {
      return;
    }
    if (backup.backup_type === "database") {
      setSaving(true);
      setInfo(null);
      try {
        await apiRequest<Job>(`/backups/${backup.id}/restore`, {
          method: "POST",
          token,
          body: {},
        });
        setInfo(locale === "ru" ? "Restore панели запущен." : "Panel restore started.");
        await loadData();
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Failed to start panel restore");
      } finally {
        setSaving(false);
      }
      return;
    }
    if (backup.backup_type === "full") {
      setSaving(true);
      setInfo(null);
      try {
        await apiRequest<Job>(`/backups/${backup.id}/restore`, {
          method: "POST",
          token,
          body: {},
        });
        setInfo(locale === "ru" ? "Restore панели из bundle запущен." : "Panel restore from bundle started.");
        await loadData();
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Failed to start panel restore from bundle");
      } finally {
        setSaving(false);
      }
      return;
    }
    const targetServerId = Number(restoreTargetByBackup[backup.id] || backup.server_id || 0);
    if (!targetServerId) {
      setError(locale === "ru" ? "Выберите сервер для restore." : "Choose a restore target server.");
      return;
    }
    setSaving(true);
    setInfo(null);
    try {
      await apiRequest<Job>(`/backups/${backup.id}/restore`, {
        method: "POST",
        token,
        body: {
          server_id: targetServerId,
        },
      });
      setInfo(locale === "ru" ? "Restore задача создана." : "Restore job created.");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to start restore");
    } finally {
      setSaving(false);
    }
  }

  async function restoreBundledServer(backup: BackupJob, bundledServer: BackupPreviewServer) {
    if (!token) {
      return;
    }
    const targetKey = `${backup.id}:${bundledServer.server_id}`;
    const targetServerId = Number(bundleTargetByBackup[targetKey] || 0);
    if (!targetServerId) {
      setError(locale === "ru" ? "Выберите целевой сервер для restore." : "Choose a target server for restore.");
      return;
    }
    setSaving(true);
    setInfo(null);
    try {
      await apiRequest<Job>(`/backups/${backup.id}/restore`, {
        method: "POST",
        token,
        body: {
          server_id: targetServerId,
          bundle_server_id: bundledServer.server_id,
        },
      });
      setInfo(locale === "ru" ? "Restore сервера из bundle запущен." : "Bundled server restore started.");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to start bundled server restore");
    } finally {
      setSaving(false);
    }
  }

  async function uploadServerBackup() {
    if (!token || !uploadFile) {
      return;
    }
    setUploading(true);
    setInfo(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("backup_type", "full");
      formData.append("archive", uploadFile);

      const response = await fetch("/api/v1/backups/upload", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: formData,
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Upload failed with status ${response.status}`);
      }
      setUploadFile(null);
      setInfo(locale === "ru" ? "Bundle загружен." : "Bundle uploaded.");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to upload backup");
    } finally {
      setUploading(false);
    }
  }

  function downloadBackup(backup: BackupJob) {
    if (!token || !backup.storage_path) {
      return;
    }
    const url = `/api/v1/backups/${backup.id}/download`;
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Download failed with status ${response.status}`);
        }
        const blob = await response.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = backup.storage_path?.split("/").pop() || `backup-${backup.id}.tar.gz`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(downloadUrl);
      })
      .catch((nextError) => {
        setError(nextError instanceof Error ? nextError.message : "Failed to download backup");
      });
  }

  async function deleteBackup(backup: BackupJob) {
    if (!token) {
      return;
    }
    setSaving(true);
    setInfo(null);
    try {
      await apiRequest<void>(`/backups/${backup.id}`, {
        method: "DELETE",
        token,
      });
      setPreviewByBackup((current) => {
        const next = { ...current };
        delete next[backup.id];
        return next;
      });
      setInfo(locale === "ru" ? "Архив удалён из панели." : "Backup removed from the panel.");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to delete backup");
    } finally {
      setSaving(false);
    }
  }

  function renderBackupCard(backup: BackupJob) {
    return (
      <article key={backup.id} className="server-card backup-card-compact">
        <div className="server-card-header">
          <div>
            <h3>#{backup.id} · {serverLabel(backup.server_id)}</h3>
            <p>{copy.createdAt}: {backup.created_at}</p>
          </div>
          <div className="action-row compact-action-row">
            <span className={`status-badge ${
              backup.status === "succeeded"
                ? "status-succeeded"
                : backup.status === "failed"
                  ? "status-failed"
                  : "status-pending"
            }`}>
              {copy.status}: {backup.status}
            </span>
            <span className="status-badge">{copy.type}: {backup.backup_type}</span>
          </div>
        </div>

        <div className="server-meta">
          <span>{copy.source}: {backupSourceLabel(backup)}</span>
          <span>{copy.storage}: {backup.storage_path ?? copy.noArchive}</span>
          {backup.result_message ? <span>{copy.result}: {backup.result_message}</span> : null}
        </div>
        {isUploadedBackup(backup) ? <div className="info-box">{copy.restoreHint}</div> : null}

        <div className="action-row">
          <button
            type="button"
            className="secondary-button"
            disabled={!backup.storage_path || backup.status !== "succeeded"}
            onClick={() => downloadBackup(backup)}
          >
            {copy.download}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={saving}
            onClick={() => void deleteBackup(backup)}
          >
            {saving ? copy.deleting : copy.delete}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={!backup.storage_path || backup.status !== "succeeded"}
            onClick={() => void togglePreview(backup)}
          >
            {previewByBackup[backup.id] ? copy.hidePreview : copy.preview}
          </button>
        </div>

        {backup.backup_type === "server" ? (
          <div className="form-grid compact-form-grid">
            <label className="field">
              <span>{copy.restoreServer}</span>
              <select
                value={restoreTargetByBackup[backup.id] ?? String(backup.server_id ?? "")}
                onChange={(event) => setRestoreTargetByBackup({ ...restoreTargetByBackup, [backup.id]: event.target.value })}
              >
                <option value=""></option>
                {backupableServers.map((server) => (
                  <option key={server.id} value={server.id}>
                    {server.name} ({server.host})
                  </option>
                ))}
              </select>
            </label>
            <div className="field field-action">
              <span>&nbsp;</span>
              <button
                type="button"
                className="primary-button"
                disabled={saving || backup.status !== "succeeded" || !backup.storage_path}
                onClick={() => void restoreBackup(backup)}
              >
                {saving ? copy.restoring : copy.restore}
              </button>
            </div>
          </div>
        ) : (
          <div className="action-row">
            <button
              type="button"
              className="primary-button"
              disabled={saving || backup.status !== "succeeded" || !backup.storage_path}
              onClick={() => void restoreBackup(backup)}
            >
              {saving ? copy.restoring : copy.restorePanel}
            </button>
          </div>
        )}

        {previewByBackup[backup.id] ? (
          <div className="info-box">
            <strong>{copy.previewTitle}</strong>
            {previewByBackup[backup.id]?.has_panel_dump ? (
              <div>{locale === "ru" ? "В архиве есть дамп панели." : "Panel dump is present in the archive."}</div>
            ) : null}
            {previewByBackup[backup.id]?.has_panel_dump && (previewByBackup[backup.id]?.servers.length ?? 0) === 0 ? (
              <div>{copy.previewPanelOnly}</div>
            ) : null}
            {(previewByBackup[backup.id]?.servers.length ?? 0) === 0 && !previewByBackup[backup.id]?.has_panel_dump ? (
              <div>{copy.previewNoServers}</div>
            ) : null}
            {(previewByBackup[backup.id]?.servers.length ?? 0) > 0 ? (
              <div>{copy.previewWithServers}</div>
            ) : null}
            {previewByBackup[backup.id]?.servers.map((bundledServer) => {
              const targetKey = `${backup.id}:${bundledServer.server_id}`;
              return (
                <div key={targetKey} style={{ marginTop: 12 }}>
                  <div>
                    {copy.bundledServer}: {bundledServer.name ?? `#${bundledServer.server_id}`}
                    {bundledServer.host ? ` (${bundledServer.host})` : ""}
                  </div>
                  <div>
                    {bundledServer.live_interface_name ?? "-"} · {bundledServer.live_config_path ?? "-"}
                    {bundledServer.has_clients_table ? " · clientsTable" : ""}
                  </div>
                  {backup.backup_type === "full" ? (
                    <div className="form-grid compact-form-grid" style={{ marginTop: 8 }}>
                      <label className="field">
                        <span>{copy.restoreServer}</span>
                        <select
                          value={bundleTargetByBackup[targetKey] ?? ""}
                          onChange={(event) => setBundleTargetByBackup({ ...bundleTargetByBackup, [targetKey]: event.target.value })}
                        >
                          <option value=""></option>
                          {backupableServers.map((server) => (
                            <option key={server.id} value={server.id}>
                              {server.name} ({server.host})
                            </option>
                          ))}
                        </select>
                      </label>
                      <div className="field field-action">
                        <span>&nbsp;</span>
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={saving || backup.status !== "succeeded" || !backup.storage_path}
                          onClick={() => void restoreBundledServer(backup, bundledServer)}
                        >
                          {saving ? copy.restoringBundleServer : copy.restoreBundleServer}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}

        {relatedJob(backup.id) ? (
          <div className="info-box">
            {copy.latestJobs}: #{relatedJob(backup.id)?.id} · {relatedJob(backup.id)?.job_type} · {relatedJob(backup.id)?.status}
          </div>
        ) : null}
      </article>
    );
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

      <section className="field-stack">
        <div className="panel-card">
          <span className="eyebrow">{copy.createTitle}</span>
          <div className="info-box">{copy.panelRestoreHint}</div>
          <div className="action-row">
            <button type="button" className="primary-button" onClick={() => void createFullBundleBackup()} disabled={saving}>
              {saving ? copy.creatingFull : copy.createFullBundle}
            </button>
          </div>
        </div>

        {backupSettings ? (
          <div className="panel-card">
            <span className="eyebrow">{copy.backupSettingsTitle}</span>
            <div className="info-box">{copy.backupSettingsHint}</div>
            <div className="form-grid compact-form-grid">
              <label className="field">
                <span>{copy.autoBackups}</span>
                <select
                  value={backupSettings.auto_backup_enabled ? "on" : "off"}
                  onChange={(event) => setBackupSettings({ ...backupSettings, auto_backup_enabled: event.target.value === "on" })}
                >
                  <option value="on">{locale === "ru" ? "Включено" : "On"}</option>
                  <option value="off">{locale === "ru" ? "Выключено" : "Off"}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.backupHourUtc}</span>
                <input
                  type="number"
                  min={0}
                  max={23}
                  value={backupSettings.auto_backup_hour_utc}
                  onChange={(event) => setBackupSettings({ ...backupSettings, auto_backup_hour_utc: Number(event.target.value) })}
                />
              </label>
              <label className="field">
                <span>{copy.retentionDays}</span>
                <input
                  type="number"
                  min={1}
                  value={backupSettings.backup_retention_days}
                  onChange={(event) => setBackupSettings({ ...backupSettings, backup_retention_days: Number(event.target.value) })}
                />
              </label>
              <div className="field field-action">
                <span>&nbsp;</span>
                <button type="button" className="primary-button" onClick={() => void saveBackupSettings()} disabled={saving}>
                  {saving ? copy.savingBackupSettings : copy.saveBackupSettings}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <div className="panel-card">
          <span className="eyebrow">{copy.uploadTitle}</span>
          <div className="info-box">{copy.uploadHint}</div>
          <div className="form-grid compact-form-grid">
            <label className="field">
              <span>{copy.chooseFile}</span>
              <input type="file" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
            </label>
            <div className="field field-action">
              <span>&nbsp;</span>
              <button type="button" className="secondary-button" onClick={() => void uploadServerBackup()} disabled={uploading || !uploadFile}>
                {uploading ? copy.uploading : copy.uploadBackup}
              </button>
            </div>
          </div>
        </div>

        <div className="panel-card">
          <span className="eyebrow">{copy.eyebrow}</span>
          <div className="backup-list-head">
            <div>
              <h3>{copy.recentBackups}</h3>
              <p>{backups.length} {copy.archiveCount}</p>
            </div>
            {olderBackups.length ? (
              <button type="button" className="secondary-button" onClick={() => setShowOlderBackups((current) => !current)}>
                {showOlderBackups ? copy.hideOlderBackups : `${copy.showOlderBackups} (${olderBackups.length})`}
              </button>
            ) : null}
          </div>
          <div className="server-list">
            {backups.length === 0 ? (
              <div className="empty-state">{copy.empty}</div>
            ) : (
              <>
                {recentBackups.map((backup) => renderBackupCard(backup))}
                {olderBackups.length > 0 && showOlderBackups ? (
                  <div className="backup-older-group">
                    <div className="backup-older-title">{copy.olderBackups}</div>
                    {olderBackups.map((backup) => renderBackupCard(backup))}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </section>
    </ProtectedApp>
  );
}
