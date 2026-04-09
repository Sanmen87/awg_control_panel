# Установка AWG Control Panel на VPS

Пошаговая инструкция для чистого сервера Ubuntu 22.04/24.04.

## Что нужно заранее

- VPS с публичным IPv4
- домен, который можно направить на этот VPS
- открытые порты:
  - `22/tcp`
  - `80/tcp`
  - `443/tcp`

## 1. Подготовить систему

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw
```

Если используешь `ufw`:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 2. Установить Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

Проверка:

```bash
docker --version
docker compose version
```

## 3. Склонировать проект

```bash
cd ~
git clone https://github.com/Sanmen87/awg_control_panel.git
cd awg_control_panel
```

## 4. Создать `.env`

В корне проекта создай `.env`.

Минимальный пример:

```env
POSTGRES_DB=awg_control_panel
POSTGRES_USER=awg
POSTGRES_PASSWORD=change-me-db

SECRET_KEY=change-me-secret-key
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=change-me-admin-password

BACKUP_STORAGE_PATH=./backups
PANEL_PUBLIC_BASE_URL=https://panel.example.com
BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://panel.example.com,https://panel.example.com

AUTH_LOGIN_MAX_ATTEMPTS=5
AUTH_LOGIN_WINDOW_SECONDS=300
AUTH_LOGIN_BAN_SECONDS=900
```

Важно:

- `SECRET_KEY` должен быть длинным и случайным
- `DEFAULT_ADMIN_PASSWORD` сразу задай нормальный
- `PANEL_PUBLIC_BASE_URL` укажи со своим доменом

## 5. Первый запуск

```bash
sudo docker compose up -d --build
```

Проверка:

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 migrate
sudo docker compose logs --tail=100 backend
```

Ожидаемо:

- `migrate` завершился успешно
- `backend`, `worker`, `scheduler`, `frontend`, `nginx` находятся в `Up`

## 6. Первый вход

Открой:

```text
http://IP_СЕРВЕРА
```

И зайди логином и паролем из `.env`.

## 7. Привязать домен

Создай `A` запись на IP сервера.

Пример:

- `panel.example.com -> 1.2.3.4`

Проверка:

```bash
dig +short panel.example.com
```

Должен вернуться IP твоего VPS.

## 8. Включить HTTPS в панели

В панели открой `Веб-интерфейс` и укажи:

- публичный домен
- email для Let's Encrypt
- режим `HTTPS`

Потом нажми:

```text
Применить и выпустить сертификат
```

Что делает кнопка:

- записывает runtime nginx-конфиг
- перезагружает nginx
- запускает `certbot`
- включает `443`

## 9. Проверить порты

На самом сервере:

```bash
sudo ss -tulpn | grep -E ':80|:443'
sudo docker compose ps
```

Снаружи:

```bash
curl -I http://panel.example.com
curl -kI https://panel.example.com
```

## 10. Проверить редирект с IP

После применения web-настроек:

```text
http://IP_СЕРВЕРА
```

должен уводить на:

```text
https://panel.example.com
```

Важно:

- `https://IP_СЕРВЕРА` без предупреждения браузера не получится, если сертификат выписан только на домен

## 11. Обновление

Полное обновление:

```bash
cd ~/awg_control_panel
git pull
sudo docker compose up -d --build
```

Если менялся только backend:

```bash
sudo docker compose up -d --build backend worker scheduler nginx
```

Если менялся frontend:

```bash
sudo docker compose up -d --build frontend nginx
```

## 12. Полезные команды

Статус:

```bash
sudo docker compose ps
```

Логи backend:

```bash
sudo docker compose logs --tail=200 backend
```

Логи nginx:

```bash
sudo docker compose logs --tail=200 nginx
```

Логи worker:

```bash
sudo docker compose logs --tail=200 worker
```

Логи миграций:

```bash
sudo docker compose logs --tail=200 migrate
```

## 13. Текущее состояние runtime

Сейчас панель уже рабочая, но важно помнить:

- frontend пока работает через `next dev`
- backend пока работает через `uvicorn --reload`
- production-hardening ещё не завершён
