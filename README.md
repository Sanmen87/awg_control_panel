# AWG Control Panel

English and Russian project overview for the current state of the repository.

## English

### Overview

`AWG Control Panel` is a Dockerized control plane for AmneziaWG / AWG infrastructure.

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
- `agent/` - reserved for future agent-side work
- `docs/` - project notes and architecture docs

### Docker services

The local stack uses:

- `db`
- `redis`
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
- server picker for managed clients now hides `exit` nodes of `proxy + 1 exit` topologies

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

### Important implementation details

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

### Default admin

Backend creates a default admin from `.env` on startup:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

---

## Русский

### Обзор

`AWG Control Panel` это Docker-панель управления для инфраструктуры AmneziaWG / AWG.

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
- `agent/` - задел под будущий агент
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
- в списке серверов для managed clients больше не показываются `exit`-ноды topology `proxy + 1 exit`

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

### Важные технические детали

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

### Админ по умолчанию

Backend при старте создаёт default admin из `.env`:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
