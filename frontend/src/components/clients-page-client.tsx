"use client";

import { FormEvent, MouseEvent, ReactNode, useEffect, useMemo, useState } from "react";

import amwgLogo from "../../logo/amWG.webp";
import amvpnLogo from "../../logo/amvpn.webp";
import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type Client = {
  id: number;
  name: string;
  public_key: string;
  assigned_ip: string;
  status: string;
  source: string;
  server_id: number | null;
  topology_id: number | null;
  expires_at: string | null;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  quiet_hours_timezone: string | null;
  import_note: string | null;
  private_key_available: boolean;
  materials_available: boolean;
  runtime_connected: boolean;
  latest_handshake_human: string | null;
  data_received_human: string | null;
  data_sent_human: string | null;
  runtime_refreshed_at: string | null;
  traffic_limit_mb: number | null;
  traffic_used_30d_rx_bytes: number;
  traffic_used_30d_tx_bytes: number;
  traffic_limit_exceeded_at: string | null;
  policy_disabled_reason: string | null;
  archived: boolean;
  delivery_email: string | null;
  delivery_telegram_chat_id: string | null;
  delivery_telegram_username: string | null;
};

type Server = {
  id: number;
  name: string;
  status: string;
  awg_detected: boolean;
  metadata_json: string | null;
};

type ImportResponse = {
  imported_count: number;
  updated_count: number;
  skipped_count: number;
  client_ids: number[];
};

type MaterialsResponse = {
  ubuntu_config: string | null;
  amneziawg_config: string | null;
  amneziavpn_config: string | null;
  qr_png_base64: string | null;
  qr_png_base64_list: string[];
  amneziawg_qr_png_base64: string | null;
  amneziawg_qr_png_base64_list: string[];
  amneziavpn_qr_png_base64: string | null;
  amneziavpn_qr_png_base64_list: string[];
};

type ServerMetadata = {
  country_code?: string;
  country_name?: string;
  city?: string;
};

type DeliverySettings = {
  delivery_email_enabled: boolean;
  delivery_telegram_enabled: boolean;
  smtp_password_configured: boolean;
  telegram_bot_token_configured: boolean;
};

type DeliveryChannelStatus = {
  kind: "success" | "error";
  text: string;
} | null;

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

function ComputerIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <rect x="4" y="5" width="16" height="11" rx="2" />
      <path d="M9 19h6" />
      <path d="M12 16v3" />
    </IconBase>
  );
}

function ImportIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M4 12h12" />
      <path d="m12 8 4 4-4 4" />
      <path d="M20 6v12" />
    </IconBase>
  );
}

function PlayIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="m9 7 8 5-8 5Z" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

function PauseIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <rect x="7" y="6" width="3.5" height="12" rx="1" fill="currentColor" stroke="none" />
      <rect x="13.5" y="6" width="3.5" height="12" rx="1" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

function TrashIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M5 7h14" />
      <path d="M9 7V5h6v2" />
      <path d="M8 7v11a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V7" />
      <path d="M10 10v6" />
      <path d="M14 10v6" />
    </IconBase>
  );
}

function CloseIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="m6 6 12 12" />
      <path d="m18 6-12 12" />
    </IconBase>
  );
}

function CircleIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <circle cx="12" cy="12" r="4.5" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

function GearIcon({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <circle cx="12" cy="12" r="2.7" />
      <path d="M12 3.8v2.1" />
      <path d="M12 18.1v2.1" />
      <path d="m18.2 5.8-1.5 1.5" />
      <path d="m7.3 16.7-1.5 1.5" />
      <path d="M20.2 12h-2.1" />
      <path d="M5.9 12H3.8" />
      <path d="m18.2 18.2-1.5-1.5" />
      <path d="m7.3 7.3-1.5-1.5" />
    </IconBase>
  );
}

export function ClientsPageClient() {
  const { token } = useAuth();
  const { locale } = useLocale();
  const [clients, setClients] = useState<Client[]>([]);
  const [servers, setServers] = useState<Server[]>([]);
  const [importServerId, setImportServerId] = useState("");
  const [newClientName, setNewClientName] = useState("");
  const [newClientServerId, setNewClientServerId] = useState("");
  const [search, setSearch] = useState("");
  const [serverFilter, setServerFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [archiveView, setArchiveView] = useState<"active" | "archived">("active");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingClientId, setSavingClientId] = useState<number | null>(null);
  const [deletingClientId, setDeletingClientId] = useState<number | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [materials, setMaterials] = useState<MaterialsResponse | null>(null);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [modalName, setModalName] = useState("");
  const [modalNote, setModalNote] = useState("");
  const [expandedQr, setExpandedQr] = useState<{
    title: string;
    image: string;
    logoSrc: string;
    logoAlt: string;
  } | null>(null);
  const [settingsClientId, setSettingsClientId] = useState<number | null>(null);
  const [trafficLimitInput, setTrafficLimitInput] = useState("");
  const [expiresAtInput, setExpiresAtInput] = useState("");
  const [quietHoursStartInput, setQuietHoursStartInput] = useState("");
  const [quietHoursEndInput, setQuietHoursEndInput] = useState("");
  const [quietHoursTimezoneInput, setQuietHoursTimezoneInput] = useState("");
  const [deliveryClientId, setDeliveryClientId] = useState<number | null>(null);
  const [deliveryEmailInput, setDeliveryEmailInput] = useState("");
  const [deliveryTelegramChatIdInput, setDeliveryTelegramChatIdInput] = useState("");
  const [deliveryTelegramUsernameInput, setDeliveryTelegramUsernameInput] = useState("");
  const [deliverySettings, setDeliverySettings] = useState<DeliverySettings | null>(null);
  const [deliveryToast, setDeliveryToast] = useState<string | null>(null);
  const [deliveryChannelLoading, setDeliveryChannelLoading] = useState<"email" | "telegram" | null>(null);
  const [deliveryEmailStatus, setDeliveryEmailStatus] = useState<DeliveryChannelStatus>(null);
  const [deliveryTelegramStatus, setDeliveryTelegramStatus] = useState<DeliveryChannelStatus>(null);

  const copy = locale === "ru"
    ? {
        title: "Импорт и управление существующими peer-клиентами.",
        refresh: "Обновить",
        importTitle: "Импорт с сервера",
        clientList: "Список клиентов",
        importButton: "Импортировать peer-ы",
        createTitle: "Новый клиент",
        createButton: "Создать клиента",
        startButton: "Запустить",
        pauseButton: "Приостановить",
        deleteButton: "Удалить",
        saveButton: "Сохранить",
        saveLimitButton: "Сохранить лимит",
        sendConfigsButton: "Отправить конфиги",
        deliveryTitle: "Доставка конфигов",
        deliveryOpenButton: "Отправить конфиг",
        deliveryEmailLabel: "Email для доставки",
        deliveryTelegramChatIdLabel: "Telegram chat id",
        deliveryTelegramUsernameLabel: "Telegram username",
        deliveryEmailSectionTitle: "Почта",
        deliveryTelegramSectionTitle: "Telegram",
        deliveryEmailChannel: "Почта",
        deliveryTelegramChannel: "Telegram",
        deliverySendingEmail: "Отправляю по почте...",
        deliverySendingTelegram: "Отправляю в Telegram...",
        deliveryNotConfigured: "Нет включённых и настроенных каналов доставки.",
        deliveryEmailUnavailable: "Канал email сейчас выключен или не настроен.",
        deliveryTelegramUnavailable: "Канал Telegram сейчас выключен или не настроен.",
        deliverySentToast: "Конфиг отправлен.",
        deliveryEmailSuccess: "Отправка по почте выполнена.",
        deliveryTelegramSuccess: "Отправка в Telegram выполнена.",
        loadingMaterials: "Загружаю материалы клиента...",
        downloadButton: "Скачать",
        enlargeQr: "Открыть QR крупно",
        trafficSettingsTitle: "Ограничение трафика",
        accessSettingsTitle: "Ограничения доступа",
        trafficLimitLabel: "Лимит за 30 дней, MiB",
        trafficLimitHint: "Оставь пустым, если лимит не нужен.",
        trafficUsageLabel: "Использовано за 30 дней",
        trafficBlockedByLimit: "Остановлен по лимиту",
        trafficLimitShort: "лимит",
        timeBlockedByPolicy: "Остановлен по времени",
        expiredByPolicy: "Срок действия истёк",
        openTrafficSettings: "Настройки трафика",
        validUntilLabel: "Действует до",
        validUntilHint: "После этой даты пир будет автоматически выключен.",
        quietHoursLabel: "Тихие часы",
        quietHoursStartLabel: "Выключать с",
        quietHoursEndLabel: "Включать в",
        quietHoursTimezoneLabel: "Часовой пояс",
        quietHoursHint: "Например: с 21:00 до 09:00.",
        noClients: "Клиенты пока не найдены.",
        searchPlaceholder: "Поиск по имени, IP, серверу или заметке",
        filtersTitle: "Фильтры",
        activeClientsTab: "Активные",
        archivedClientsTab: "Архивные",
        allServers: "Все серверы",
        allSources: "Все источники",
        allStatuses: "Все статусы",
        fields: {
          server: "Сервер",
          name: "Имя",
          source: "Источник",
          status: "Статус",
          runtime: "Сеть",
          traffic: "Трафик",
          limits: "Ограничения",
          actions: "Действия",
          ip: "IP",
          note: "Заметка"
        },
        noLimits: "Без ограничений",
        trafficLimitState: "Лимит трафика",
        timeLimitState: "Лимит времени",
        untilLabel: "до",
        imported: "Импортирован",
        generated: "Сгенерирован",
        online: "онлайн",
        offline: "офлайн",
        importSummary: "Импорт завершен",
        importHint: "Панель подтянет существующие peer-ы с сервера и сохранит их как клиентов.",
        createHint: "Создание управляемого клиента с сохранением конфигов и QR в базе.",
        materialsTitle: "Материалы клиента",
        qrHint: "Если QR несколько, сканируй их по порядку.",
        awgQrTitle: "QR для AmneziaWG",
        vpnQrTitle: "QR для AmneziaVPN",
        configsTitle: "Конфиги",
        noTopology: "не привязан",
        emptyFiltered: "По текущим фильтрам ничего не найдено.",
        emptyArchived: "Архивных клиентов пока нет.",
        deleteConfirm: "Удалить клиента? Peer будет удален и из серверного конфига.",
        runtimeUnknown: "ожидание данных",
        notAvailableTitle: "Материалы недоступны",
        importedNoMaterials: "Это импортированный peer. На сервере нет приватного ключа клиента, поэтому панель не может восстановить конфиги и QR.",
        generatedNoMaterials: "Для этого клиента материалы пока не подготовлены.",
        close: "Закрыть"
      }
    : {
        title: "Import and manage existing peer clients.",
        refresh: "Refresh",
        importTitle: "Import from server",
        clientList: "Client list",
        importButton: "Import peers",
        createTitle: "New client",
        createButton: "Create client",
        startButton: "Start",
        pauseButton: "Pause",
        deleteButton: "Delete",
        saveButton: "Save",
        saveLimitButton: "Save limit",
        sendConfigsButton: "Send configs",
        deliveryTitle: "Config delivery",
        deliveryOpenButton: "Send config",
        deliveryEmailLabel: "Delivery email",
        deliveryTelegramChatIdLabel: "Telegram chat id",
        deliveryTelegramUsernameLabel: "Telegram username",
        deliveryEmailSectionTitle: "Email",
        deliveryTelegramSectionTitle: "Telegram",
        deliveryEmailChannel: "Email",
        deliveryTelegramChannel: "Telegram",
        deliverySendingEmail: "Sending email...",
        deliverySendingTelegram: "Sending Telegram...",
        deliveryNotConfigured: "No enabled and configured delivery channels.",
        deliveryEmailUnavailable: "Email delivery is currently disabled or not configured.",
        deliveryTelegramUnavailable: "Telegram delivery is currently disabled or not configured.",
        deliverySentToast: "Config sent.",
        deliveryEmailSuccess: "Email delivery completed.",
        deliveryTelegramSuccess: "Telegram delivery completed.",
        loadingMaterials: "Loading client materials...",
        downloadButton: "Download",
        enlargeQr: "Open QR in large view",
        trafficSettingsTitle: "Traffic limit",
        accessSettingsTitle: "Access restrictions",
        trafficLimitLabel: "30-day limit, MiB",
        trafficLimitHint: "Leave empty if no limit is needed.",
        trafficUsageLabel: "Used over 30 days",
        trafficBlockedByLimit: "Paused by limit",
        trafficLimitShort: "limit",
        timeBlockedByPolicy: "Paused by time policy",
        expiredByPolicy: "Expired",
        openTrafficSettings: "Traffic settings",
        validUntilLabel: "Valid until",
        validUntilHint: "After this date the peer will be automatically disabled.",
        quietHoursLabel: "Quiet hours",
        quietHoursStartLabel: "Disable from",
        quietHoursEndLabel: "Enable at",
        quietHoursTimezoneLabel: "Timezone",
        quietHoursHint: "Example: from 21:00 to 09:00.",
        noClients: "No clients found yet.",
        searchPlaceholder: "Search by name, IP, server, or note",
        filtersTitle: "Filters",
        activeClientsTab: "Active",
        archivedClientsTab: "Archived",
        allServers: "All servers",
        allSources: "All sources",
        allStatuses: "All statuses",
        fields: {
          server: "Server",
          name: "Name",
          source: "Source",
          status: "Status",
          runtime: "Network",
          traffic: "Traffic",
          limits: "Limits",
          actions: "Actions",
          ip: "IP",
          note: "Note"
        },
        noLimits: "No limits",
        trafficLimitState: "Traffic limit",
        timeLimitState: "Time limit",
        untilLabel: "until",
        imported: "Imported",
        generated: "Generated",
        online: "online",
        offline: "offline",
        importSummary: "Import completed",
        importHint: "The panel will pull existing peers from the server and store them as clients.",
        createHint: "Create a managed client and store configs and QR in the database.",
        materialsTitle: "Client materials",
        qrHint: "If there are several QR codes, scan them in order.",
        awgQrTitle: "QR for AmneziaWG",
        vpnQrTitle: "QR for AmneziaVPN",
        configsTitle: "Configs",
        noTopology: "unassigned",
        emptyFiltered: "No clients match the current filters.",
        emptyArchived: "No archived clients yet.",
        deleteConfirm: "Delete this client? The peer will be removed from the server config.",
        runtimeUnknown: "waiting for data",
        notAvailableTitle: "Materials unavailable",
        importedNoMaterials: "This is an imported peer. The panel does not have the client's private key, so configs and QR cannot be reconstructed.",
        generatedNoMaterials: "Materials have not been prepared for this client yet.",
        close: "Close"
      };

  const selectedClient = useMemo(
    () => clients.find((client) => client.id === selectedClientId) ?? null,
    [clients, selectedClientId]
  );
  const settingsClient = useMemo(
    () => clients.find((client) => client.id === settingsClientId) ?? null,
    [clients, settingsClientId]
  );
  const deliveryClient = useMemo(
    () => clients.find((client) => client.id === deliveryClientId) ?? null,
    [clients, deliveryClientId]
  );

  async function loadData() {
    if (!token) {
      return;
    }
    try {
      const [nextClients, nextServers, nextDeliverySettings] = await Promise.all([
        apiRequest<Client[]>(`/clients?archived=${archiveView === "archived" ? "true" : "false"}`, { token }),
        apiRequest<Server[]>("/servers", { token }),
        apiRequest<DeliverySettings>("/settings/delivery", { token }),
      ]);
      setClients(nextClients);
      setServers(nextServers);
      setDeliverySettings(nextDeliverySettings);
      if (selectedClientId) {
        const current = nextClients.find((client) => client.id === selectedClientId);
        if (current) {
          setModalName(current.name);
          setModalNote(current.import_note ?? "");
        }
      }
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load clients");
    }
  }

  useEffect(() => {
    void loadData();
    if (!token) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadData();
    }, 60000);
    return () => window.clearInterval(intervalId);
  }, [token, selectedClientId, archiveView]);

  useEffect(() => {
    closeModal();
    closeSettingsModal();
  }, [archiveView]);

  useEffect(() => {
    if (!selectedClient) {
      return;
    }
    setModalName(selectedClient.name);
    setModalNote(selectedClient.import_note ?? "");
  }, [selectedClient]);

  function serverName(serverId: number | null) {
    if (!serverId) {
      return "-";
    }
    return servers.find((server) => server.id === serverId)?.name ?? `#${serverId}`;
  }

  function serverMetadata(serverId: number | null) {
    if (!serverId) {
      return null;
    }
    const server = servers.find((item) => item.id === serverId);
    if (!server?.metadata_json) {
      return null;
    }
    try {
      return JSON.parse(server.metadata_json) as ServerMetadata;
    } catch {
      return null;
    }
  }

  function flagForCountry(countryCode?: string) {
    if (!countryCode) {
      return null;
    }
    if (countryCode === "LAN") {
      return "🖧";
    }
    if (!/^[A-Z]{2}$/.test(countryCode)) {
      return null;
    }
    return String.fromCodePoint(...Array.from(countryCode).map((char) => 127397 + char.charCodeAt(0)));
  }

  function geoTitle(metadata: ServerMetadata | null) {
    if (!metadata?.country_code) {
      return null;
    }
    if (metadata.country_code === "LAN") {
      return locale === "ru" ? "Локальная сеть" : "Local network";
    }
    if (metadata.country_name && metadata.city) {
      return `${metadata.country_name}, ${metadata.city}`;
    }
    return metadata.country_name ?? null;
  }

  function sourceTooltip(source: string) {
    return source === "imported" ? copy.imported : copy.generated;
  }

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !importServerId) {
      return;
    }
    setLoading(true);
    try {
      const result = await apiRequest<ImportResponse>("/clients/import", {
        method: "POST",
        token,
        body: { server_id: Number(importServerId) }
      });
      setInfo(
        `${copy.importSummary}: +${result.imported_count} / ~${result.updated_count} / skip ${result.skipped_count}`
      );
      setError(null);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to import peers");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateManagedClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !newClientName || !newClientServerId) {
      return;
    }
    setLoading(true);
    try {
      await apiRequest<Client>("/clients/managed", {
        method: "POST",
        token,
        body: {
          name: newClientName,
          server_id: Number(newClientServerId)
        }
      });
      setInfo(`${copy.createButton}: ${newClientName}`);
      setNewClientName("");
      setNewClientServerId("");
      setError(null);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to create managed client");
    } finally {
      setLoading(false);
    }
  }

  async function saveClient(client: Client) {
    if (!token) {
      return;
    }
    setSavingClientId(client.id);
    try {
      await apiRequest<Client>(`/clients/${client.id}`, {
        method: "PATCH",
        token,
        body: {
          name: modalName.trim() || client.name,
          status: client.status,
          import_note: modalNote.trim() || null
        }
      });
      setInfo(`${copy.saveButton}: ${modalName.trim() || client.name}`);
      setError(null);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to update client");
    } finally {
      setSavingClientId(null);
    }
  }

  async function updateClientStatus(client: Client, nextStatus: string) {
    if (!token) {
      return;
    }
    setSavingClientId(client.id);
    try {
      await apiRequest<Client>(`/clients/${client.id}`, {
        method: "PATCH",
        token,
        body: {
          name: client.id === selectedClientId ? (modalName.trim() || client.name) : client.name,
          status: nextStatus,
          import_note: client.id === selectedClientId ? (modalNote.trim() || null) : client.import_note
        }
      });
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to update client status");
    } finally {
      setSavingClientId(null);
    }
  }

  async function deleteClient(client: Client) {
    if (!token || !window.confirm(copy.deleteConfirm)) {
      return;
    }
    setDeletingClientId(client.id);
    try {
      await apiRequest<void>(`/clients/${client.id}`, {
        method: "DELETE",
        token
      });
      if (selectedClientId === client.id) {
        closeModal();
      }
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to delete client");
    } finally {
      setDeletingClientId(null);
    }
  }

  async function openClientModal(client: Client) {
    if (!token) {
      return;
    }
    setSelectedClientId(client.id);
    setModalName(client.name);
    setModalNote(client.import_note ?? "");
    setMaterials(null);
    setMaterialsLoading(true);
    try {
      const nextMaterials = await apiRequest<MaterialsResponse>(`/clients/${client.id}/materials`, { token });
      setMaterials(nextMaterials);
      setError(null);
    } catch (nextError) {
      setMaterials(null);
      setError(nextError instanceof Error ? nextError.message : "Failed to load client materials");
    } finally {
      setMaterialsLoading(false);
    }
  }

  function closeModal() {
    setSelectedClientId(null);
    setMaterials(null);
    setMaterialsLoading(false);
    setModalName("");
    setModalNote("");
    setExpandedQr(null);
    closeDeliveryModal();
  }

  function closeSettingsModal() {
    setSettingsClientId(null);
    setTrafficLimitInput("");
    setExpiresAtInput("");
    setQuietHoursStartInput("");
    setQuietHoursEndInput("");
    setQuietHoursTimezoneInput("");
    setDeliveryEmailInput("");
    setDeliveryTelegramChatIdInput("");
    setDeliveryTelegramUsernameInput("");
  }

  function openDeliveryModal(client: Client) {
    setDeliveryClientId(client.id);
    setDeliveryEmailInput(client.delivery_email ?? "");
    setDeliveryTelegramChatIdInput(client.delivery_telegram_chat_id ?? "");
    setDeliveryTelegramUsernameInput(client.delivery_telegram_username ?? "");
    setDeliveryEmailStatus(null);
    setDeliveryTelegramStatus(null);
    setDeliveryChannelLoading(null);
  }

  function closeDeliveryModal() {
    setDeliveryClientId(null);
    setDeliveryEmailInput("");
    setDeliveryTelegramChatIdInput("");
    setDeliveryTelegramUsernameInput("");
    setDeliveryEmailStatus(null);
    setDeliveryTelegramStatus(null);
    setDeliveryChannelLoading(null);
  }

  function stopRowClick(event: MouseEvent<HTMLElement>) {
    event.stopPropagation();
  }

  function makeDownloadName(client: Client, suffix: string, extension: string) {
    const safeName = client.name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/gi, "-")
      .replace(/^-+|-+$/g, "") || `client-${client.id}`;
    return `${safeName}-${suffix}.${extension}`;
  }

  function downloadTextFile(content: string, fileName: string) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function formatBytes(value: number) {
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let size = Math.max(value, 0);
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    if (unitIndex === 0) {
      return `${Math.round(size)} ${units[unitIndex]}`;
    }
    return `${size.toFixed(2)} ${units[unitIndex]}`;
  }

  function formatDateTime(value: string | null) {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return new Intl.DateTimeFormat(locale === "ru" ? "ru-RU" : "en-US", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date);
  }

  function toDateTimeLocalValue(value: string | null) {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return localDate.toISOString().slice(0, 16);
  }

  function renderLimitState(client: Client) {
    const parts: string[] = [];
    if (client.traffic_limit_mb) {
      parts.push(`${copy.trafficLimitState}: ${client.traffic_limit_mb} MiB / 30d`);
    }
    if (client.expires_at) {
      parts.push(`${copy.timeLimitState}: ${copy.untilLabel} ${formatDateTime(client.expires_at)}`);
    }
    if (client.quiet_hours_start && client.quiet_hours_end) {
      parts.push(`${copy.quietHoursLabel}: ${client.quiet_hours_start}-${client.quiet_hours_end} ${client.quiet_hours_timezone ?? "UTC"}`);
    }
    if (parts.length === 0) {
      return copy.noLimits;
    }
    return parts.join(" · ");
  }

  function openSettingsModal(client: Client) {
    setSettingsClientId(client.id);
    setTrafficLimitInput(client.traffic_limit_mb ? String(client.traffic_limit_mb) : "");
    setExpiresAtInput(toDateTimeLocalValue(client.expires_at));
    setQuietHoursStartInput(client.quiet_hours_start ?? "");
    setQuietHoursEndInput(client.quiet_hours_end ?? "");
    setQuietHoursTimezoneInput(client.quiet_hours_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
    setDeliveryEmailInput(client.delivery_email ?? "");
    setDeliveryTelegramChatIdInput(client.delivery_telegram_chat_id ?? "");
    setDeliveryTelegramUsernameInput(client.delivery_telegram_username ?? "");
  }

  async function saveTrafficLimit(client: Client) {
    if (!token) {
      return;
    }
    const parsedLimit = trafficLimitInput.trim() ? Number(trafficLimitInput.trim()) : null;
    if (parsedLimit !== null && (!Number.isFinite(parsedLimit) || parsedLimit < 0)) {
      setError("Traffic limit must be a non-negative number");
      return;
    }
    setSavingClientId(client.id);
    try {
      await apiRequest<Client>(`/clients/${client.id}`, {
        method: "PATCH",
        token,
        body: {
          name: client.name,
          status: client.status,
          import_note: client.import_note,
          delivery_email: deliveryEmailInput.trim() || null,
          delivery_telegram_chat_id: deliveryTelegramChatIdInput.trim() || null,
          delivery_telegram_username: deliveryTelegramUsernameInput.trim() || null,
          traffic_limit_mb: parsedLimit === null ? null : Math.round(parsedLimit),
          expires_at: expiresAtInput ? new Date(expiresAtInput).toISOString() : null,
          quiet_hours_start: quietHoursStartInput.trim() || null,
          quiet_hours_end: quietHoursEndInput.trim() || null,
          quiet_hours_timezone:
            quietHoursStartInput.trim() || quietHoursEndInput.trim()
              ? (quietHoursTimezoneInput.trim() || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC")
              : null
        }
      });
      setError(null);
      setInfo(`${copy.saveLimitButton}: ${client.name}`);
      closeSettingsModal();
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to update traffic limit");
    } finally {
      setSavingClientId(null);
    }
  }

  async function deliverClientConfigs(client: Client, channels: string[]) {
    if (!token) {
      return;
    }
    const channel = channels[0] === "telegram" ? "telegram" : "email";
    setSavingClientId(client.id);
    setDeliveryChannelLoading(channel);
    if (channel === "email") {
      setDeliveryEmailStatus(null);
    } else {
      setDeliveryTelegramStatus(null);
    }
    try {
      await apiRequest<Client>(`/clients/${client.id}`, {
        method: "PATCH",
        token,
        body: {
          name: client.name,
          status: client.status,
          import_note: client.import_note,
          delivery_email: deliveryEmailInput.trim() || null,
          delivery_telegram_chat_id: deliveryTelegramChatIdInput.trim() || null,
          delivery_telegram_username: deliveryTelegramUsernameInput.trim() || null,
          traffic_limit_mb: client.traffic_limit_mb,
          expires_at: client.expires_at,
          quiet_hours_start: client.quiet_hours_start,
          quiet_hours_end: client.quiet_hours_end,
          quiet_hours_timezone: client.quiet_hours_timezone,
        }
      });
      const result = await apiRequest<Record<string, string>>(`/clients/${client.id}/deliver-configs`, {
        method: "POST",
        token,
        body: { channels },
      });
      setInfo(`${copy.sendConfigsButton}: ${Object.entries(result).map(([key, value]) => `${key}=${value}`).join(", ")}`);
      setDeliveryToast(`${copy.deliverySentToast} ${Object.entries(result).map(([key, value]) => `${key}=${value}`).join(", ")}`);
      window.setTimeout(() => setDeliveryToast(null), 2600);
      if (channel === "email") {
        setDeliveryEmailStatus({ kind: "success", text: copy.deliveryEmailSuccess });
      } else {
        setDeliveryTelegramStatus({ kind: "success", text: copy.deliveryTelegramSuccess });
      }
      setError(null);
      await loadData();
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to deliver configs";
      setError(message);
      if (channel === "email") {
        setDeliveryEmailStatus({ kind: "error", text: message });
      } else {
        setDeliveryTelegramStatus({ kind: "error", text: message });
      }
    } finally {
      setSavingClientId(null);
      setDeliveryChannelLoading(null);
    }
  }

  const emailDeliveryAvailable = Boolean(deliverySettings?.delivery_email_enabled && deliverySettings?.smtp_password_configured);
  const telegramDeliveryAvailable = Boolean(deliverySettings?.delivery_telegram_enabled && deliverySettings?.telegram_bot_token_configured);

  function policyReasonLabel(reason: string | null) {
    if (reason === "traffic_limit") {
      return copy.trafficBlockedByLimit;
    }
    if (reason === "quiet_hours") {
      return copy.timeBlockedByPolicy;
    }
    if (reason === "expired") {
      return copy.expiredByPolicy;
    }
    return null;
  }

  const filteredClients = useMemo(() => {
    const query = search.trim().toLowerCase();
    return clients.filter((client) => {
      if (serverFilter && String(client.server_id ?? "") !== serverFilter) {
        return false;
      }
      if (sourceFilter !== "all" && client.source !== sourceFilter) {
        return false;
      }
      if (statusFilter !== "all" && client.status !== statusFilter) {
        return false;
      }
      if (!query) {
        return true;
      }

      const haystack = [
        client.name,
        client.assigned_ip,
        client.import_note ?? "",
        serverName(client.server_id)
      ]
        .join(" ")
        .toLowerCase();

      return haystack.includes(query);
    });
  }, [clients, search, serverFilter, sourceFilter, statusFilter, servers]);

  return (
    <ProtectedApp
      sidebarExtra={
        <>
          <form className="sidebar-panel" onSubmit={handleCreateManagedClient}>
            <span className="eyebrow">{copy.createTitle}</span>
            <p>{copy.createHint}</p>
            <label className="field">
              <span>{copy.fields.name}</span>
              <input value={newClientName} onChange={(event) => setNewClientName(event.target.value)} required />
            </label>
            <label className="field">
              <span>{copy.fields.server}</span>
              <select value={newClientServerId} onChange={(event) => setNewClientServerId(event.target.value)} required>
                <option value=""></option>
                {servers
                  .filter((server) => server.awg_detected)
                  .map((server) => (
                    <option key={server.id} value={server.id}>
                      {server.name}
                    </option>
                  ))}
              </select>
            </label>
            <button type="submit" className="primary-button" disabled={loading}>
              {copy.createButton}
            </button>
          </form>

          <form className="sidebar-panel" onSubmit={handleImport}>
            <span className="eyebrow">{copy.importTitle}</span>
            <p>{copy.importHint}</p>
            <label className="field">
              <span>{copy.fields.server}</span>
              <select value={importServerId} onChange={(event) => setImportServerId(event.target.value)} required>
                <option value=""></option>
                {servers.map((server) => (
                  <option key={server.id} value={server.id}>
                    {server.name} ({server.status}, AWG {server.awg_detected ? "ok" : "missing"})
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="primary-button" disabled={loading}>
              {copy.importButton}
            </button>
          </form>
        </>
      }
    >
      <div className="page-header">
        <div>
          <span className="eyebrow">Clients</span>
          <h2>{copy.title}</h2>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadData()}>
          {copy.refresh}
        </button>
      </div>

      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="info-box">{info}</div> : null}
      {deliveryToast ? <div className="clients-floating-toast">{deliveryToast}</div> : null}

      <section className="clients-page-section">
        <div className="panel-card clients-list-panel">
          <div className="clients-archive-head">
            <div className="clients-archive-toggle">
              <button
                type="button"
                className={`secondary-button ${archiveView === "active" ? "is-selected" : ""}`}
                onClick={() => setArchiveView("active")}
              >
                {copy.activeClientsTab}
              </button>
              <button
                type="button"
                className={`secondary-button ${archiveView === "archived" ? "is-selected" : ""}`}
                onClick={() => setArchiveView("archived")}
              >
                {copy.archivedClientsTab}
              </button>
            </div>
            <span className="eyebrow">{copy.clientList}</span>
          </div>

          <div className="client-filters">
            <div className="client-filters-header">{copy.filtersTitle}</div>
            <div className="client-filters-grid">
              <label className="field field-wide">
                <span>{copy.searchPlaceholder}</span>
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={copy.searchPlaceholder}
                />
              </label>
              <label className="field">
                <span>{copy.fields.server}</span>
                <select value={serverFilter} onChange={(event) => setServerFilter(event.target.value)}>
                  <option value="">{copy.allServers}</option>
                  {servers.map((server) => (
                    <option key={server.id} value={server.id}>
                      {server.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>{copy.fields.source}</span>
                <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                  <option value="all">{copy.allSources}</option>
                  <option value="imported">{copy.imported}</option>
                  <option value="generated">{copy.generated}</option>
                </select>
              </label>
              <label className="field">
                <span>{copy.fields.status}</span>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="all">{copy.allStatuses}</option>
                  <option value="active">active</option>
                  <option value="disabled">disabled</option>
                  <option value="revoked">revoked</option>
                </select>
              </label>
            </div>
          </div>

          {clients.length === 0 ? (
            <div className="empty-state">{archiveView === "archived" ? copy.emptyArchived : copy.noClients}</div>
          ) : filteredClients.length === 0 ? (
            <div className="empty-state">{archiveView === "archived" ? copy.emptyArchived : copy.emptyFiltered}</div>
          ) : (
            <div className="clients-table-wrap">
              <table className="clients-table clients-compact-table">
                <thead>
                  <tr>
                    <th>{copy.fields.name}</th>
                    <th>{copy.fields.server}</th>
                    <th>{copy.fields.ip}</th>
                    <th>{copy.fields.source}</th>
                    <th>{copy.fields.runtime}</th>
                    <th>{copy.fields.status}</th>
                    <th>{copy.fields.traffic}</th>
                    <th>{copy.fields.limits}</th>
                    <th>{copy.fields.note}</th>
                    <th>{copy.fields.actions}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredClients.map((client) => (
                    <tr key={client.id} className="clients-row-clickable" onClick={() => void openClientModal(client)}>
                      <td className="clients-cell-name">
                        <div className="clients-primary-text">{client.name}</div>
                        <div className="clients-secondary-text">{client.latest_handshake_human ?? copy.runtimeUnknown}</div>
                      </td>
                      <td>
                        <span className="server-cell-with-flag">
                          {flagForCountry(serverMetadata(client.server_id)?.country_code) ? (
                            <span className="country-flag" title={geoTitle(serverMetadata(client.server_id)) ?? undefined}>
                              {flagForCountry(serverMetadata(client.server_id)?.country_code)}
                            </span>
                          ) : null}
                          <span>{serverName(client.server_id)}</span>
                        </span>
                      </td>
                      <td className="clients-cell-mono">{client.assigned_ip}</td>
                      <td>
                        <span className="clients-icon-chip" title={sourceTooltip(client.source)}>
                          {client.source === "imported" ? <ImportIcon className="clients-inline-icon" /> : <ComputerIcon className="clients-inline-icon" />}
                        </span>
                      </td>
                      <td>
                        <div className="clients-runtime-stack" title={client.runtime_connected ? copy.online : copy.offline}>
                          <CircleIcon className={`clients-runtime-dot ${client.runtime_connected ? "is-online" : "is-offline"}`} />
                          <span className="clients-runtime-meta">{client.latest_handshake_human ?? "—"}</span>
                        </div>
                      </td>
                      <td>
                        <div className="clients-runtime-stack">
                          <span
                            className={`clients-icon-chip ${client.traffic_limit_exceeded_at ? "is-limit-exceeded" : ""}`}
                            title={policyReasonLabel(client.policy_disabled_reason) ?? client.status}
                          >
                            {client.status === "active"
                              ? <PlayIcon className="clients-status-icon is-play" />
                              : <PauseIcon className={`clients-status-icon ${client.traffic_limit_exceeded_at ? "is-limit" : "is-pause"}`} />}
                          </span>
                          {policyReasonLabel(client.policy_disabled_reason) ? (
                            <span className="clients-runtime-meta">{policyReasonLabel(client.policy_disabled_reason)}</span>
                          ) : null}
                        </div>
                      </td>
                      <td className="clients-cell-note">
                        <div className="clients-traffic-stack">
                          <span>
                            {client.data_received_human || client.data_sent_human
                              ? `${client.data_received_human ?? "0"} / ${client.data_sent_human ?? "0"}`
                              : "—"}
                          </span>
                          <span className="clients-secondary-text">
                            {formatBytes(client.traffic_used_30d_rx_bytes + client.traffic_used_30d_tx_bytes)}
                          </span>
                        </div>
                      </td>
                      <td className="clients-cell-note">{renderLimitState(client)}</td>
                      <td className="clients-cell-note">{client.import_note?.trim() || "—"}</td>
                      <td>
                        <div className="clients-icon-actions" onClick={stopRowClick}>
                          <button
                            type="button"
                            className={`clients-icon-button ${
                              client.traffic_limit_mb || client.expires_at || (client.quiet_hours_start && client.quiet_hours_end)
                                ? "is-settings-active"
                                : "is-muted"
                            }`}
                            onClick={() => openSettingsModal(client)}
                            title={copy.openTrafficSettings}
                            disabled={archiveView === "archived"}
                          >
                            <GearIcon className="clients-action-icon" />
                          </button>
                          <button
                            type="button"
                            className={`clients-icon-button ${client.status === "active" ? "is-muted" : "is-play"}`}
                            disabled={archiveView === "archived" || savingClientId === client.id || client.status === "active"}
                            onClick={() => void updateClientStatus(client, "active")}
                            title={copy.startButton}
                          >
                            <PlayIcon className="clients-action-icon" />
                          </button>
                          <button
                            type="button"
                            className={`clients-icon-button ${client.status === "active" ? "is-pause" : "is-muted"}`}
                            disabled={archiveView === "archived" || savingClientId === client.id || client.status !== "active"}
                            onClick={() => void updateClientStatus(client, "disabled")}
                            title={copy.pauseButton}
                          >
                            <PauseIcon className="clients-action-icon" />
                          </button>
                          <button
                            type="button"
                            className="clients-icon-button is-delete"
                            disabled={archiveView === "archived" || deletingClientId === client.id}
                            onClick={() => void deleteClient(client)}
                            title={copy.deleteButton}
                          >
                            <TrashIcon className="clients-action-icon" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {selectedClient ? (
        <div className="clients-modal-backdrop" onClick={closeModal}>
          <div className="clients-modal" onClick={stopRowClick}>
            <div className="clients-modal-header">
              <div>
                <span className="eyebrow">{copy.materialsTitle}</span>
                <h3>{selectedClient.name}</h3>
              </div>
              <button type="button" className="clients-icon-button is-muted" onClick={closeModal} title={copy.close}>
                <CloseIcon className="clients-action-icon" />
              </button>
            </div>

            <div className="clients-modal-scroll">
              <div className="clients-modal-grid">
                <div className="clients-modal-sidebar">
                  <label className="field">
                    <span>{copy.fields.name}</span>
                    <input value={modalName} onChange={(event) => setModalName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>{copy.fields.note}</span>
                    <textarea
                      className="clients-note-input"
                      value={modalNote}
                      onChange={(event) => setModalNote(event.target.value)}
                      rows={5}
                    />
                  </label>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={savingClientId === selectedClient.id}
                    onClick={() => void saveClient(selectedClient)}
                  >
                    {copy.saveButton}
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => openDeliveryModal(selectedClient)}
                  >
                    {copy.deliveryOpenButton}
                  </button>
                </div>

                <div className="clients-modal-content">
                  {materialsLoading ? (
                    <div className="empty-state">{copy.loadingMaterials}</div>
                  ) : materials && (materials.amneziawg_config || materials.amneziavpn_config) ? (
                    <>
                      <div className="client-materials-panel">
                        {materials.amneziawg_qr_png_base64_list.length > 0 ? (
                          <section className="clients-modal-section">
                            <div className="clients-modal-section-head">
                              <img src={amwgLogo.src} alt="AmneziaWG" className="clients-material-logo" />
                              <span className="eyebrow">{copy.awgQrTitle}</span>
                            </div>
                            {materials.amneziawg_qr_png_base64_list.length > 1 ? <p>{copy.qrHint}</p> : null}
                            <div className="client-qr-list">
                              {materials.amneziawg_qr_png_base64_list.map((qrImage, index) => (
                                <button
                                  key={`awg-${selectedClient.id}-${index}`}
                                  type="button"
                                  className="client-qr-button"
                                  onClick={() =>
                                    setExpandedQr({
                                      title: `AmneziaWG QR ${index + 1}`,
                                      image: `data:image/png;base64,${qrImage}`,
                                      logoSrc: amwgLogo.src,
                                      logoAlt: "AmneziaWG"
                                    })
                                  }
                                  title={copy.enlargeQr}
                                >
                                  <img
                                    className="client-qr-image"
                                    src={`data:image/png;base64,${qrImage}`}
                                    alt={`AmneziaWG QR ${index + 1}`}
                                  />
                                </button>
                              ))}
                            </div>
                          </section>
                        ) : null}

                        {materials.amneziavpn_qr_png_base64_list.length > 0 ? (
                          <section className="clients-modal-section">
                            <div className="clients-modal-section-head">
                              <img src={amvpnLogo.src} alt="AmneziaVPN" className="clients-material-logo" />
                              <span className="eyebrow">{copy.vpnQrTitle}</span>
                            </div>
                            {materials.amneziavpn_qr_png_base64_list.length > 1 ? <p>{copy.qrHint}</p> : null}
                            <div className="client-qr-list">
                              {materials.amneziavpn_qr_png_base64_list.map((qrImage, index) => (
                                <button
                                  key={`vpn-${selectedClient.id}-${index}`}
                                  type="button"
                                  className="client-qr-button"
                                  onClick={() =>
                                    setExpandedQr({
                                      title: `AmneziaVPN QR ${index + 1}`,
                                      image: `data:image/png;base64,${qrImage}`,
                                      logoSrc: amvpnLogo.src,
                                      logoAlt: "AmneziaVPN"
                                    })
                                  }
                                  title={copy.enlargeQr}
                                >
                                  <img
                                    className="client-qr-image"
                                    src={`data:image/png;base64,${qrImage}`}
                                    alt={`AmneziaVPN QR ${index + 1}`}
                                  />
                                </button>
                              ))}
                            </div>
                          </section>
                        ) : null}

                      <section className="clients-modal-section">
                        <span className="eyebrow">{copy.configsTitle}</span>
                        {materials.ubuntu_config ? (
                          <details className="preview-item" open>
                            <summary>Ubuntu / AWG</summary>
                              <div className="clients-material-actions">
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() =>
                                    downloadTextFile(
                                      materials.ubuntu_config as string,
                                      makeDownloadName(selectedClient, "ubuntu-awg", "conf")
                                    )
                                  }
                                >
                                  {copy.downloadButton} `.conf`
                                </button>
                              </div>
                              <pre className="log-box">{materials.ubuntu_config}</pre>
                            </details>
                          ) : null}
                          {materials.amneziawg_config ? (
                            <details className="preview-item">
                              <summary>AmneziaWG</summary>
                              <div className="clients-material-actions">
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() =>
                                    downloadTextFile(
                                      materials.amneziawg_config as string,
                                      makeDownloadName(selectedClient, "amneziawg", "conf")
                                    )
                                  }
                                >
                                  {copy.downloadButton} `.conf`
                                </button>
                              </div>
                              <pre className="log-box">{materials.amneziawg_config}</pre>
                            </details>
                          ) : null}
                          {materials.amneziavpn_config ? (
                            <details className="preview-item">
                              <summary>AmneziaVPN</summary>
                              <div className="clients-material-actions">
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() =>
                                    downloadTextFile(
                                      materials.amneziavpn_config as string,
                                      makeDownloadName(selectedClient, "amneziavpn", "vpn")
                                    )
                                  }
                                >
                                  {copy.downloadButton} `.vpn`
                                </button>
                              </div>
                              <pre className="log-box">{materials.amneziavpn_config}</pre>
                            </details>
                          ) : null}
                        </section>
                      </div>
                    </>
                  ) : (
                    <div className="clients-empty-materials">
                      <span className="eyebrow">{copy.notAvailableTitle}</span>
                      <p>{selectedClient.source === "imported" ? copy.importedNoMaterials : copy.generatedNoMaterials}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {expandedQr ? (
        <div className="clients-qr-overlay" onClick={() => setExpandedQr(null)}>
          <div className="clients-qr-dialog" onClick={stopRowClick}>
            <div className="clients-modal-header">
              <div>
                <span className="eyebrow">{expandedQr.title}</span>
                <h3>{selectedClient?.name ?? ""}</h3>
              </div>
              <button
                type="button"
                className="clients-icon-button is-muted"
                onClick={() => setExpandedQr(null)}
                title={copy.close}
              >
                <CloseIcon className="clients-action-icon" />
              </button>
            </div>
            <div className="clients-qr-dialog-body">
              <div className="clients-qr-dialog-brand">
                <img src={expandedQr.logoSrc} alt={expandedQr.logoAlt} className="clients-qr-dialog-logo" />
                <span className="eyebrow">{expandedQr.logoAlt}</span>
              </div>
              <img className="clients-qr-image-large" src={expandedQr.image} alt={expandedQr.title} />
            </div>
          </div>
        </div>
      ) : null}

      {settingsClient ? (
        <div className="clients-qr-overlay" onClick={closeSettingsModal}>
          <div className="clients-settings-dialog" onClick={stopRowClick}>
            <div className="clients-modal-header">
              <div>
                <span className="eyebrow">{copy.accessSettingsTitle}</span>
                <h3>{settingsClient.name}</h3>
              </div>
              <button
                type="button"
                className="clients-icon-button is-muted"
                onClick={closeSettingsModal}
                title={copy.close}
              >
                <CloseIcon className="clients-action-icon" />
              </button>
            </div>
            <div className="clients-settings-body">
              <label className="field">
                <span>{copy.trafficLimitLabel}</span>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={trafficLimitInput}
                  onChange={(event) => setTrafficLimitInput(event.target.value)}
                  placeholder="20480"
                />
              </label>
              <p className="clients-settings-hint">{copy.trafficLimitHint}</p>
              <label className="field">
                <span>{copy.validUntilLabel}</span>
                <input
                  type="datetime-local"
                  value={expiresAtInput}
                  onChange={(event) => setExpiresAtInput(event.target.value)}
                />
              </label>
              <p className="clients-settings-hint">{copy.validUntilHint}</p>
              <div className="clients-settings-grid">
                <label className="field">
                  <span>{copy.quietHoursStartLabel}</span>
                  <input
                    type="time"
                    value={quietHoursStartInput}
                    onChange={(event) => setQuietHoursStartInput(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>{copy.quietHoursEndLabel}</span>
                  <input
                    type="time"
                    value={quietHoursEndInput}
                    onChange={(event) => setQuietHoursEndInput(event.target.value)}
                  />
                </label>
              </div>
              <label className="field">
                <span>{copy.quietHoursTimezoneLabel}</span>
                <input
                  value={quietHoursTimezoneInput}
                  onChange={(event) => setQuietHoursTimezoneInput(event.target.value)}
                  placeholder="Europe/Moscow"
                />
              </label>
              <p className="clients-settings-hint">{copy.quietHoursHint}</p>
              <div className="clients-settings-metric">
                <span className="eyebrow">{copy.trafficUsageLabel}</span>
                <strong>{formatBytes(settingsClient.traffic_used_30d_rx_bytes + settingsClient.traffic_used_30d_tx_bytes)}</strong>
                <span className="clients-secondary-text">
                  RX {formatBytes(settingsClient.traffic_used_30d_rx_bytes)} / TX {formatBytes(settingsClient.traffic_used_30d_tx_bytes)}
                </span>
              </div>
              {settingsClient.traffic_limit_exceeded_at ? (
                <div className="error-box">{copy.trafficBlockedByLimit}</div>
              ) : null}
              {settingsClient.policy_disabled_reason === "quiet_hours" ? (
                <div className="info-box">{copy.timeBlockedByPolicy}</div>
              ) : null}
              {settingsClient.policy_disabled_reason === "expired" ? (
                <div className="error-box">{copy.expiredByPolicy}</div>
              ) : null}
              <div className="action-row compact-action-row">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={closeSettingsModal}
                >
                  {copy.close}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={savingClientId === settingsClient.id}
                  onClick={() => void saveTrafficLimit(settingsClient)}
                >
                  {copy.saveLimitButton}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {deliveryClient ? (
        <div className="clients-qr-overlay" onClick={closeDeliveryModal}>
          <div className="clients-settings-dialog" onClick={stopRowClick}>
            <div className="clients-modal-header">
              <div>
                <span className="eyebrow">{copy.deliveryTitle}</span>
                <h3>{deliveryClient.name}</h3>
              </div>
              <button
                type="button"
                className="clients-icon-button is-muted"
                onClick={closeDeliveryModal}
                title={copy.close}
              >
                <CloseIcon className="clients-action-icon" />
              </button>
            </div>
            <div className="clients-settings-body">
              {!emailDeliveryAvailable && !telegramDeliveryAvailable ? (
                <div className="info-box">{copy.deliveryNotConfigured}</div>
              ) : null}
              <section className="clients-modal-section">
                <span className="eyebrow">{copy.deliveryEmailSectionTitle}</span>
                <label className="field">
                  <span>{copy.deliveryEmailLabel}</span>
                  <input value={deliveryEmailInput} onChange={(event) => setDeliveryEmailInput(event.target.value)} />
                </label>
                {emailDeliveryAvailable ? (
                  <div className="clients-delivery-actions">
                    <button
                      type="button"
                      className="primary-button"
                      disabled={savingClientId === deliveryClient.id}
                      onClick={() => void deliverClientConfigs(deliveryClient, ["email"])}
                    >
                      {deliveryChannelLoading === "email" ? copy.deliverySendingEmail : copy.deliveryEmailChannel}
                    </button>
                  </div>
                ) : (
                  <div className="info-box">{copy.deliveryEmailUnavailable}</div>
                )}
                {deliveryEmailStatus ? (
                  <div className={deliveryEmailStatus.kind === "success" ? "info-box" : "error-box"}>
                    {deliveryEmailStatus.text}
                  </div>
                ) : null}
              </section>
              <section className="clients-modal-section">
                <span className="eyebrow">{copy.deliveryTelegramSectionTitle}</span>
                <label className="field">
                  <span>{copy.deliveryTelegramChatIdLabel}</span>
                  <input value={deliveryTelegramChatIdInput} onChange={(event) => setDeliveryTelegramChatIdInput(event.target.value)} />
                </label>
                <label className="field">
                  <span>{copy.deliveryTelegramUsernameLabel}</span>
                  <input value={deliveryTelegramUsernameInput} onChange={(event) => setDeliveryTelegramUsernameInput(event.target.value)} />
                </label>
                {telegramDeliveryAvailable ? (
                  <div className="clients-delivery-actions">
                    <button
                      type="button"
                      className="primary-button"
                      disabled={savingClientId === deliveryClient.id}
                      onClick={() => void deliverClientConfigs(deliveryClient, ["telegram"])}
                    >
                      {deliveryChannelLoading === "telegram" ? copy.deliverySendingTelegram : copy.deliveryTelegramChannel}
                    </button>
                  </div>
                ) : (
                  <div className="info-box">{copy.deliveryTelegramUnavailable}</div>
                )}
                {deliveryTelegramStatus ? (
                  <div className={deliveryTelegramStatus.kind === "success" ? "info-box" : "error-box"}>
                    {deliveryTelegramStatus.text}
                  </div>
                ) : null}
              </section>
              <div className="action-row compact-action-row">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={closeDeliveryModal}
                >
                  {copy.close}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </ProtectedApp>
  );
}
