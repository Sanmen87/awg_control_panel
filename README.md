# AWG Control Panel

English and Russian project overview for the current state of the repository.

[EN](#english) / [RU](#русский)

## English

### Overview

`AWG Control Panel` is a Dockerized control plane for AmneziaWG / AWG infrastructure.

Current repository status: fully working MVP.

Current stack:

- `backend`: FastAPI, SQLAlchemy, Alembic, Celery
- `frontend`: Next.js
- `database`: PostgreSQL
- `queue`: Redis
- `reverse proxy`: nginx

Repository layout:

- `backend/` - API, models, services, workers, migrations
- `frontend/` - admin UI
- `infra/` - nginx config and deployment assets
- `agent/` - per-server agent notes and runtime direction
- `docs/` - project notes and architecture docs
- `документация/` - operational install notes in Russian

### Docker services

The local stack uses:

- `db`
- `redis`
- `migrate`
- `backend`
- `worker`
- `scheduler`
- `frontend`
- `nginx`

Main entrypoints:

- UI: `http://localhost`
- API health: `http://localhost/api/v1/health`

### Quick start

1. Copy `.env.example` to `.env`
2. Start the stack

```bash
docker compose up --build
```

On a fresh machine the stack now runs database migrations through a dedicated one-shot `migrate` service before `backend`, `worker`, and `scheduler` start. This avoids the old initial migration race on an empty PostgreSQL volume.

For rebuild after backend or frontend changes:

```bash
sudo docker compose build backend worker scheduler frontend
sudo docker compose up -d backend worker scheduler frontend nginx
```

### What is implemented now

#### Servers

- server CRUD in panel
- SSH connectivity checks
- AWG detection
- docker-based Amnezia detection
- panel-managed install modes:
  - `docker`
  - `go`
  - `custom` is treated as import/adoption only
- live config import from existing server
- correct detection of `amnezia-awg`
- server geolocation with local `IP2Location LITE DB3 BIN`
- server country flag shown in UI

#### Docker install branch

The `docker` installation branch was rewritten.

Previous behavior:

- the panel built a custom local container which effectively embedded the `go` toolchain and AWG tools inside Docker

Current behavior:

- the panel follows an upstream-like Amnezia client flow instead of the old custom `go-in-docker` bootstrap
- host preparation creates:
  - `/opt/amnezia/amnezia-awg`
  - `/opt/amnezia/amnezia-dns`
  - docker network `amnezia-dns-net`
- `amnezia-awg` is now built from an upstream-like Dockerfile based on:
  - `amneziavpn/amneziawg-go:latest`
- `amnezia-dns` is now built from an upstream-like Dockerfile based on:
  - `mvance/unbound:latest`
- containers are started in the same general order as the official `amnezia-client` flow:
  - prepare host
  - build images
  - run `amnezia-dns`
  - run `amnezia-awg`
  - connect `amnezia-awg` to `amnezia-dns-net`

Notes:

- the panel still keeps `/opt/amnezia/awg` for compatibility with current import, `clientsTable`, and runtime sync logic
- the branch is now much closer to the official AmneziaVPN server bootstrap, but post-install runtime behavior should still be validated end-to-end on a clean external server

#### Topologies

- topology wizard UX
- support for imported standard topology flow
- adopt existing imported `wg0.conf` instead of blind overwrite
- preview and deploy for imported standard docker server
- working `proxy + 1 exit` flow
- separate service tunnel on proxy:
  - `awg0` stays the client-facing interface
  - `awgN` is used as proxy-to-exit service link
- dedicated policy-routing table on proxy for proxy clients
- service peer is injected into the exit live config without replacing normal exit clients
- topology deploy now cleans stale proxy-side `MASQUERADE` and old service-peer leftovers
- bootstrap now re-inspects live runtime automatically so a freshly installed server becomes usable without a second manual prepare step
- topology deploy now ignores panel infrastructure containers when resolving docker AWG runtime
- docker topology apply now resolves real in-container config paths instead of trying to write to `docker://...`
- server picker for managed clients now hides `exit` nodes of `proxy + 1 exit` topologies
- topology metadata now includes proxy routing mode for proxy topologies:
  - `all via exit`
  - `selective via exit`
- selective proxy routing is implemented for `proxy + 1 exit` and `proxy + multi-exit`
  - current route source is static `backend/routip/routes.txt`
  - addresses from that list go through exit
  - all other destinations use the proxy server local uplink
  - current practical route set includes:
    - Telegram
    - Google
    - Netflix
    - OpenAI
    - Twitter/X
    - Discord
- selective routing runtime on proxy now manages:
  - `ipset`
  - `iptables mangle` marking
  - per-exit policy tables
- proxy failover agent is now selective-aware:
  - it no longer reintroduces conflicting source-based rules in selective mode
  - it restarts cleanly on reinstall
  - in multi-exit mode it can rebuild selective default-path marking for the active exit

#### Clients

- import peers from server
- parse and use `clientsTable`
- managed client creation
- managed client disable / enable / delete
- rename and notes editing
- configs stored in DB for managed clients
- QR stored/generated for managed clients
- separate QR flows for:
  - `AmneziaWG`
  - `AmneziaVPN`
- downloadable config materials:
  - `Ubuntu / AWG` as `.conf`
  - `AmneziaWG` as `.conf`
  - `AmneziaVPN` as `.vpn`
- imported peers are shown, but config/QR reconstruction is not possible without the private key

#### Runtime stats

- periodic Celery sync every minute
- runtime pull from `awg show all dump` / `wg show all dump`
- live online/offline state
- latest handshake display
- RX/TX display in panel
- raw runtime samples stored in DB
- rolling 30-day traffic usage stored per client

#### Limits and policy controls

- per-client traffic limit for rolling 30 days
- soft disable when traffic limit is exceeded
- `valid until` restriction
- quiet-hours restriction such as `21:00 -> 09:00`
- policy-driven disable reasons:
  - `traffic_limit`
  - `expired`
  - `quiet_hours`
- manual disable is stored separately from policy disable
- peer comments in adopted `wg0.conf` include policy metadata

#### Frontend

- bilingual UI (`RU` / `EN`)
- clients table redesigned into compact icon-driven layout
- click row to open client materials modal
- separate settings modal from gear icon
- QR enlarge-on-click
- source, runtime, status, and actions shown with unified pictograms
- mobile interface foundation is implemented:
  - separate `mobile.css` override layer
  - mobile drawer navigation
  - mobile bottom control bar
  - clients list adapted into stacked cards on narrow screens
- topology editor UI now includes:
  - proxy routing mode selector for proxy topologies
  - updated copy for the current single compatible AWG profile
  - updated selective-routing helper text reflecting the current static route list
- separate sidebar route for `Backups`
- separate sidebar route for `Web / HTTPS`
- panel web publishing settings are now separated from delivery settings
- frontend Docker build now uses a dedicated `dev` target so local / VPS dev runtime no longer bakes the whole source tree into the image
- frontend Dockerfile now supports:
  - `dev` target for `next dev`
  - `builder` target for `next build`
  - `runner` target for standalone production runtime
- frontend dependency layer now prefers `npm ci` when `package-lock.json` exists
- frontend build context is constrained by `frontend/.dockerignore`

#### Docker Runtime Hygiene

- compose enables Docker log rotation for the main services:
  - `max-size: 10m`
  - `max-file: 3`
- this prevents unbounded growth of container `json-file` logs on small VPS disks
- frontend named volumes are used for:
  - `node_modules`
  - `.next`
- current practical disk-growth watchpoints on small VPS nodes are:
  - Docker build cache
  - large rebuilt images
  - `journald`
- the current operational cleanup commands are:

```bash
docker builder prune -af
journalctl --vacuum-size=200M
```

#### Web / HTTPS

- separate `Web / HTTPS` page in the sidebar
- stored settings:
  - public domain
  - Let's Encrypt email
  - HTTP / HTTPS mode
- live diagnostics:
  - DNS resolution
  - port `80`
  - port `443`
  - certificate presence and expiry
- generated nginx config preview in UI
- apply flow now:
  - writes runtime nginx config
  - reloads nginx
  - in `HTTPS` mode runs `certbot` with `webroot`
- generated config also adds canonical HTTP redirect from server IP or unknown host to the configured domain
- nginx reload during web apply now uses the Docker socket API instead of depending on the `docker` CLI inside backend

Notes:

- `http://SERVER_IP` can be redirected to the domain
- `https://SERVER_IP` still cannot be made clean without a certificate for the IP itself

#### Auth Protection

- Redis-backed anti-bruteforce guard on admin login
- failed login counters by:
  - client IP
  - username
- temporary login ban after repeated failures
- configurable env settings:
  - `AUTH_LOGIN_MAX_ATTEMPTS`
  - `AUTH_LOGIN_WINDOW_SECONDS`
  - `AUTH_LOGIN_BAN_SECONDS`
- audit events are written to `audit_logs`:
  - `auth_login_failed`
  - `auth_login_banned`
  - `auth_login_blocked`

#### Backups

- `full bundle` is the main backup format
- bundle includes:
  - panel PostgreSQL dump
  - server runtime/config snapshots when available
  - unified `manifest.json`
- backup storage path is configured through `BACKUP_STORAGE_PATH`
- automatic backup retention and cleanup are supported
- uploaded bundles are handled separately in UI
- restore flow is manual and bundle-oriented:
  - panel restore from uploaded bundle
  - selected server restore from uploaded bundle
- local/generated backups are not mixed into the restore list in the UI

#### Extra Services

- separate main-menu section: `Extra services`
- currently implemented services:
  - `MTProxy`
  - `SOCKS5`
  - `Xray / VLESS + Reality`
- eligible targets:
  - exit nodes of proxy topologies
  - standalone standard servers
- current MTProxy mode is practical `script-mode`
  - uses `telegrammessenger/proxy`
  - uses Fake TLS secret in `ee...` format
  - requires a short domain up to 15 bytes, for example `vk.com` or `ya.ru`
- panel can:
  - install MTProxy on a server
  - show endpoint, mode, tg-link and linked install job
  - refresh live status from server
  - delete MTProxy both from panel and from server
  - send MTProxy access link by email
- SOCKS5 is available as a secondary extra service:
  - docker-based install on the same eligible nodes
  - generated username / password
  - refresh status, delete from server, and email delivery
- Xray is available in `VLESS + Reality` mode:
  - docker-based install
  - generated `UUID`, `shortId`, and `x25519` keypair
  - ready-to-import `vless://` link for clients with Reality support
  - current practical mask-domain default is `www.apple.com`
  - current tested working path is suitable for iPhone clients
- current manual status refresh checks the remote Docker container over SSH
- current delete flow removes:
  - container `awg-mtproxy-*`
  - remote directory `/opt/awg-extra-services/mtproxy-*`
- current install UI is presented as three aligned service cards
  - shared white card layout
  - aligned install actions
  - copy-to-clipboard action in connection blocks for MTProxy and Xray

#### Per-server agent

- hybrid per-server agent foundation is implemented
- agent install is SSH-driven from the panel
- new servers get the agent during bootstrap
- existing servers can install the agent from the server card
- existing servers can also reinstall the agent from the server card after runtime updates
- current hybrid mode supports:
  - local SSH/local-results mode when panel agent API is not exposed externally
  - API sync mode when the panel exposes a stable public agent endpoint
- current local agent stores:
  - `agent-status.json`
  - local queued tasks
  - local task results
  - `client-policies.json`
  - `client-policy-state.json`
- current allowlisted handlers:
  - `collect-runtime-snapshot`
  - `collect-traffic-counters`
  - `read-clients-table`
  - `inspect-standard-runtime`
  - `enforce-client-policies`
- current panel-side usage:
  - server card shows agent status
  - manual actions:
    - install agent
    - reinstall agent
    - reinstall agent
    - refresh agent status
    - fetch local results
- current hybrid data paths:
  - server runtime metrics prefer local agent results and fall back to SSH
  - client runtime sync prefers local agent results and falls back to SSH
  - `prepare` / `inspect-standard` prefer local agent inspect and fall back to SSH
- current offline-policy direction:
  - panel syncs client policy snapshot to the server
  - agent can enforce traffic, expiry, and quiet-hours policies locally
  - panel can later reconcile offline-collected policy state back into DB
- SSH is still used for:
  - install/bootstrap
  - upload/apply operations
  - restore/backup write paths
- current near-term direction is to formalize the mode switch:
  - without a public agent-facing panel endpoint, the agent stays in local SSH-driven mode
  - with a public agent-facing panel endpoint, the same agent can switch into API sync mode
- planned next agent policy layer:
  - per-peer bandwidth limits through agent-managed `tc` shaping
  - shaping keyed by client `assigned_ip`

### Important implementation details

#### Agent operating modes

- panel installs and updates the agent over SSH
- agent executes only allowlisted task handlers
- no arbitrary shell is accepted from API
- each server has its own token
- if panel does not expose an agent-facing web/API page, the agent works in local mode:
  - local files
  - SSH-driven fetch/apply paths
- if panel exposes an agent-facing web/API page, the same agent can switch to API sync mode for heartbeat, task/result exchange, and status updates

#### Real server paths

The current imported-server flow is based on:

- docker container: `amnezia-awg`
- config path: `/opt/amnezia/awg/wg0.conf`
- clients table path: `/opt/amnezia/awg/clientsTable`

#### Imported clients

Imported peers do not have private keys available on the server.

This means:

- imported peers can be listed and controlled
- imported peers can be tracked for runtime stats
- imported peers cannot get reconstructed config files or QR unless the panel originally generated and stored their private key

#### GeoIP

GeoIP uses local database lookup instead of external HTTP calls.

Current database file:

- `backend/geo/IP2LOCATION-LITE-DB3.BIN`

Implementation:

- [`backend/app/services/server_geo.py`](/home/sarov/projects/awg_control_panel/backend/app/services/server_geo.py)

Dependency:

- `IP2Location==8.11.0`

### Migrations

If startup does not auto-apply migrations, check Alembic state manually.

Recent client-related migrations include:

- client materials and PSK storage
- runtime stats fields
- raw runtime samples and rolling usage
- time restrictions and policy disable reason
- manual disable flag

### Current limitations

- frontend local production build may fail in an incomplete local `node_modules` environment if `next` is missing
- imported peers still cannot provide config downloads or QR
- traffic accounting starts from the moment runtime sampling is enabled, not retroactively
- policy disable and manual disable are now separated in backend, but the UI can still be refined further for clearer status visualization
- `proxy + 1 exit` requires the proxy client subnet not to overlap with existing peer `AllowedIPs` on the chosen exit server
- if an existing exit already has peers inside the same subnet as proxy clients, topology validation will now block deploy until the overlap is removed

### Roadmap / To-do

- move more read-only SSH checks to agent handlers
- decide which write paths must stay SSH-only
- add clearer agent task/status UI
- define conflict-resolution rules for:
  - traffic counters collected offline
  - task execution results produced while panel connectivity was lost
  - server-side state drift between panel and agent

### Default admin

Backend creates a default admin from `.env` on startup:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

### Server install

For a step-by-step VPS install guide in Russian see:

- [server_install_ru.md](/home/sarov/projects/awg_control_panel/документация/server_install_ru.md)

---

## Русский

### Обзор

`AWG Control Panel` это Docker-панель управления для инфраструктуры AmneziaWG / AWG.

Текущий статус репозитория: полностью рабочее MVP.

Текущий стек:

- `backend`: FastAPI, SQLAlchemy, Alembic, Celery
- `frontend`: Next.js
- `database`: PostgreSQL
- `queue`: Redis
- `reverse proxy`: nginx

Структура репозитория:

- `backend/` - API, модели, сервисы, воркеры, миграции
- `frontend/` - административный UI
- `infra/` - конфиги nginx и deployment assets
- `agent/` - заметки и направление развития серверного агента
- `docs/` - заметки по проекту и архитектуре

### Docker-сервисы

Локальный стек использует:

- `db`
- `redis`
- `backend`
- `worker`
- `scheduler`
- `frontend`
- `nginx`

Основные точки входа:

- UI: `http://localhost`
- API health: `http://localhost/api/v1/health`

### Быстрый старт

1. Скопировать `.env.example` в `.env`
2. Поднять стек

```bash
docker compose up --build
```

Для пересборки после изменений backend/frontend:

```bash
sudo docker compose build backend worker scheduler frontend
sudo docker compose up -d backend worker scheduler frontend nginx
```

### Что уже реализовано

#### Серверы

- CRUD серверов в панели
- SSH check
- детект AWG
- docker-based детект Amnezia
- panel-managed режимы установки:
  - `docker`
  - `go`
  - `custom` считается только сценарием импорта/адаптации
- импорт live-конфига с уже существующего сервера
- корректное определение контейнера `amnezia-awg`
- геолокация сервера по локальной базе `IP2Location LITE DB3 BIN`
- флаги страны сервера в UI

#### Docker-ветка установки

Ветка установки `docker` была переписана.

Раньше:

- панель собирала собственный локальный контейнер, который по сути повторял `go`-ветку внутри Docker

Сейчас:

- панель использует flow, приближенный к официальному `amnezia-client`, а не старый кастомный bootstrap `go-in-docker`
- при подготовке хоста создаются:
  - `/opt/amnezia/amnezia-awg`
  - `/opt/amnezia/amnezia-dns`
  - docker-сеть `amnezia-dns-net`
- `amnezia-awg` теперь собирается из upstream-like Dockerfile на базе:
  - `amneziavpn/amneziawg-go:latest`
- `amnezia-dns` теперь собирается из upstream-like Dockerfile на базе:
  - `mvance/unbound:latest`
- контейнеры поднимаются в том же общем порядке, что и в официальном `amnezia-client`:
  - подготовка хоста
  - сборка образов
  - запуск `amnezia-dns`
  - запуск `amnezia-awg`
  - подключение `amnezia-awg` к `amnezia-dns-net`

Примечания:

- для совместимости с текущими import/runtime-механизмами панель по-прежнему использует `/opt/amnezia/awg`
- ветка стала заметно ближе к официальному bootstrap AmneziaVPN, но post-install runtime поведение всё ещё нужно валидировать end-to-end на чистом внешнем сервере

#### Топологии

- wizard UX
- сценарий imported standard topology
- adoption существующего `wg0.conf` вместо слепой перезаписи
- preview и deploy для imported standard docker server
- рабочий сценарий `proxy + 1 exit`
- отдельный service tunnel на proxy:
  - `awg0` остаётся клиентским интерфейсом
  - `awgN` используется как service link `proxy -> exit`
- отдельная policy-routing таблица на proxy для клиентской подсети proxy
- `service-peer` добавляется в live config `exit` без потери обычных клиентов exit-ноды
- deploy topology теперь чистит stale `MASQUERADE` на proxy и старые service-peer хвосты
- после bootstrap сервер теперь автоматически переинспектируется и становится пригодным для topology / managed clients без второго ручного `Подготовить сервер`
- topology deploy больше не путает контейнеры самой панели с `amnezia-awg`
- для docker-topology теперь используется реальный путь конфига внутри контейнера, а не псевдо-путь вида `docker://...`
- в списке серверов для managed clients больше не показываются `exit`-ноды topology `proxy + 1 exit`
- metadata topology теперь хранит режим маршрутизации proxy:
  - `всё через exit`
  - `только список через exit`
- selective routing реализован для:
  - `proxy + 1 exit`
  - `proxy + multi-exit`
- текущий источник маршрутов статичный:
  - [routes.txt](awg_control_panel/backend/routip/routes.txt)
- сейчас через exit идут адреса для:
  - `Telegram`
  - `Google`
  - `Netflix`
  - `OpenAI`
  - `Twitter/X`
  - `Discord`
- остальной трафик клиентов выходит напрямую через интернет proxy-сервера
- runtime selective routing на proxy сейчас управляет:
  - `ipset`
  - `iptables mangle`
  - отдельными per-exit policy tables
- `proxy_failover_agent` теперь учитывает selective mode:
  - не возвращает конфликтующие source-based `ip rule`
  - перезапускается при reinstall новым кодом
  - в `multi-exit` умеет пересобрать default selective path под активный exit

#### Клиенты

- импорт peer-клиентов с сервера
- парсинг и использование `clientsTable`
- создание managed client
- disable / enable / delete managed client
- rename и редактирование заметок
- хранение конфигов managed clients в БД
- хранение / генерация QR для managed clients
- отдельные QR-сценарии для:
  - `AmneziaWG`
  - `AmneziaVPN`
- скачивание материалов:
  - `Ubuntu / AWG` как `.conf`
  - `AmneziaWG` как `.conf`
  - `AmneziaVPN` как `.vpn`
- imported peer-клиенты отображаются, но восстановить их конфиг или QR нельзя без приватного ключа

#### Runtime-статистика

- периодическая Celery-задача раз в минуту
- чтение runtime из `awg show all dump` / `wg show all dump`
- live online/offline статус
- отображение latest handshake
- отображение RX/TX в панели
- хранение сырых runtime samples в БД
- хранение rolling traffic usage за 30 дней по каждому клиенту

#### Ограничения и policy control

- лимит трафика на клиента за rolling 30 days
- мягкая остановка peer при превышении лимита
- ограничение `действует до`
- ограничение quiet-hours, например `21:00 -> 09:00`
- причины policy-disable:
  - `traffic_limit`
  - `expired`
  - `quiet_hours`
- ручная пауза хранится отдельно от policy-disable
- в комментарии peer внутри adopted `wg0.conf` пишется metadata по ограничениям

#### Frontend

- двуязычный UI (`RU` / `EN`)
- таблица клиентов переделана в компактный icon-driven вид
- клик по строке открывает модалку материалов клиента
- отдельная модалка настроек по шестерёнке
- QR можно увеличить кликом
- источник, runtime, статус и действия показаны через единый набор пиктограмм
- реализована базовая мобильная версия интерфейса:
  - отдельный слой `mobile.css`
  - mobile drawer-навигация
  - нижняя управляющая mobile-панель
  - список клиентов на узком экране превращается в набор карточек
- редактор topology теперь показывает:
  - selector режима маршрутизации proxy
  - обновлённый helper по AWG profile
  - обновлённый helper по selective routing под текущий статичный список
- настройки публикации панели в веб вынесены в отдельную страницу `Web / HTTPS`

#### Web / HTTPS

- отдельная страница `Web / HTTPS` в боковом меню
- хранятся настройки:
  - публичный домен
  - email для Let's Encrypt
  - режим `HTTP / HTTPS`
- есть live-диагностика:
  - DNS
  - порт `80`
  - порт `443`
  - наличие и срок действия TLS-сертификата
- в UI показывается preview генерируемого nginx-конфига
- apply-сценарий теперь:
  - пишет runtime nginx config
  - перегружает nginx
  - в режиме `HTTPS` запускает `certbot` через `webroot`
- в nginx-конфиг также добавляется канонический HTTP-редирект с IP сервера или неизвестного host на настроенный домен
- reload nginx в этом сценарии теперь делается через Docker socket API, а не через вызов `docker` CLI из backend

#### Бэкапы

- основной формат резервной копии сейчас: `full bundle`
- bundle включает:
  - дамп PostgreSQL панели
  - snapshots конфигов/runtime серверов, если они доступны
  - единый `manifest.json`
- путь хранения архивов задаётся через `BACKUP_STORAGE_PATH`
- поддерживаются retention и автоочистка архивов
- загруженные bundle-архивы в UI обрабатываются отдельно
- restore сейчас ручной и bundle-ориентированный:
  - restore панели из загруженного bundle
  - restore выбранного сервера из загруженного bundle
- локально созданные архивы не смешиваются в UI со списком restore-архивов

#### Доп сервисы

- отдельный раздел основного меню: `Доп сервисы`
- сейчас реализованы сервисы:
  - `MTProxy`
  - `SOCKS5`
  - `Xray / VLESS + Reality`
- разрешённые цели установки:
  - exit-ноды proxy-topology
  - standalone standard-серверы
- текущий режим MTProxy: практический `script-mode` работает в текущих российских реалиях
  - используется `telegrammessenger/proxy`
  - используется Fake TLS secret формата `ee...`
  - нужен короткий домен до 15 байт, например `vk.com` или `ya.ru`
- панель умеет:
  - ставить MTProxy на сервер
  - показывать endpoint, режим, tg-link и связанную install-задачу
  - вручную обновлять live-статус с сервера
  - удалять MTProxy и из панели, и с сервера
  - отправлять ссылку доступа по email
- `SOCKS5` доступен как второй допсервис:
  - docker-установка на те же допустимые серверы
  - автогенерация логина и пароля
  - refresh status, удаление с сервера и email delivery
- `Xray` доступен в режиме `VLESS + Reality`:
  - docker-установка
  - генерация `UUID`, `shortId` и `x25519` keypair
  - готовая `vless://` ссылка для импорта в клиенты с поддержкой Reality
  - текущий практический домен по умолчанию: `www.apple.com`
  - текущий проверенный рабочий сценарий подходит для iPhone-клиентов
- ручная проверка статуса сейчас идёт по SSH через проверку remote Docker container
- при удалении сейчас также удаляются:
  - контейнер `awg-mtproxy-*`
  - remote directory `/opt/awg-extra-services/mtproxy-*`
- UI установки сейчас приведён к общему карточному виду для трёх сервисов:
  - одинаковая белая подложка
  - выровненные install-кнопки
  - copy-to-clipboard в блоках подключения для MTProxy и Xray

#### Серверный агент

- реализован foundation для гибридного per-server агента
- агент ставится по SSH со стороны панели
- на новых серверах он ставится во время bootstrap
- на старых серверах его можно поставить отдельной кнопкой из карточки сервера
- текущий гибридный режим поддерживает:
  - локальный SSH/local-results режим, если у панели нет внешней agent API страницы
  - API sync режим, если у панели есть стабильная внешняя agent API страница
- локально агент сейчас ведёт:
  - `agent-status.json`
  - очередь локальных задач
  - локальные результаты задач
- текущие allowlisted handlers:
  - `collect-runtime-snapshot`
  - `collect-traffic-counters`
  - `read-clients-table`
  - `inspect-standard-runtime`
- что уже использует панель:
  - карточка сервера показывает статус агента
  - ручные действия:
    - установить агент
    - переустановить агент
    - установить агент
    - проверить агента
    - забрать результаты
- текущие hybrid data paths:
  - server runtime metrics сначала идут через результаты агента, потом через SSH fallback
  - sync клиентского runtime сначала идёт через результаты агента, потом через SSH fallback
  - `prepare` / `inspect-standard` сначала идут через локальный inspect агента, потом через SSH fallback
- SSH пока остаётся для:
  - install/bootstrap
  - upload/apply операций
  - restore/backup write path
- ближайшее направление развития агента: формализовать переключение режима:
  - без внешней agent API страницы агент остаётся в локальном SSH-режиме
  - при наличии внешней agent API страницы тот же агент переключается в API sync режим

### Важные технические детали

#### Режимы работы агента

- панель ставит и обновляет агент по SSH
- агент выполняет только allowlisted handlers
- никакого произвольного shell из API нет
- у каждого сервера свой token
- если у панели нет внешней agent API страницы, агент работает в локальном режиме:
  - локальные файлы статуса и результатов
  - SSH-driven fetch/apply paths
- если у панели есть внешняя agent API страница, тот же агент может переключиться в API sync режим для heartbeat, обмена задачами/результатами и статусов

#### Реальные пути на сервере

Текущий imported-server сценарий опирается на:

- docker container: `amnezia-awg`
- config path: `/opt/amnezia/awg/wg0.conf`
- clients table path: `/opt/amnezia/awg/clientsTable`

#### Imported clients

У imported peer-клиентов на сервере нет приватных ключей.

Это значит:

- imported peer можно показывать и администрировать
- можно собирать их runtime-статистику
- но нельзя восстановить конфиг и QR, если панель не генерировала и не сохраняла private key сама

#### GeoIP

GeoIP работает через локальную базу, а не через внешний HTTP lookup.

Файл базы:

- `backend/geo/IP2LOCATION-LITE-DB3.BIN`

Реализация:

- [`backend/app/services/server_geo.py`](/home/sarov/projects/awg_control_panel/backend/app/services/server_geo.py)

Зависимость:

- `IP2Location==8.11.0`

### Миграции

Если миграции не применяются автоматически при старте, нужно отдельно проверить состояние Alembic.

Последние клиентские миграции покрывают:

- хранение client materials и PSK
- runtime stats поля
- raw runtime samples и rolling usage
- временные ограничения и причину policy-disable
- флаг manual disable

### Текущие ограничения

- локальная production-сборка фронта может не пройти в неполном `node_modules`, если отсутствует `next`
- imported peer-клиентам по-прежнему нельзя выдавать конфиги и QR
- точный traffic accounting начинается с момента включения runtime sampling, а не задним числом
- backend уже разделяет manual disable и policy disable, но UI ещё можно дополнительно улучшить для более наглядного отображения статусов
- для `proxy + 1 exit` подсеть клиентов proxy не должна пересекаться с уже существующими `AllowedIPs` peer-клиентов на exit-сервере
- если на existing exit уже есть peer в той же подсети, topology validation теперь блокирует deploy до устранения конфликта

### Планы / To-do

- перевести на agent больше read-only SSH checks
- определить, какие write-path операции должны навсегда остаться SSH-only
- сделать более явный UI статусов и задач агента
- реализовать чёткое переключение агента между режимами:
  - локальный SSH/local-results режим без внешней agent API страницы
  - API sync режим при наличии внешней agent API страницы
- отдельно определить правила разрешения конфликтов для:
  - traffic counters, накопленных офлайн
  - результатов задач, выполненных во время потери связи с панелью
  - расхождения server-side состояния между панелью и агентом

### Админ по умолчанию

Backend при старте создаёт default admin из `.env`:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
