# External API

## Purpose

The external API is intended for service-to-service integrations which need to:

- discover available topology targets for client creation
- create managed clients in simple and proxy topologies
- list clients and generated materials
- suspend, resume, and delete managed clients

The external API does not replace the regular panel UI. It uses the same client records and must not break normal client management from the panel.

## Prerequisites

- enable external API in `Web / HTTPS` settings
- generate or rotate the external API token on the same page
- store the raw token immediately; it is shown only once

Base URL examples below use:

```text
https://panel.example.com
```

Authentication:

```bash
curl -H "Authorization: Bearer <TOKEN>" https://panel.example.com/api/v1/external/servers
```

Alternative header:

```bash
curl -H "X-API-Token: <TOKEN>" https://panel.example.com/api/v1/external/servers
```

If the external API toggle is off, all `/api/v1/external/*` requests return `403`.

## Scopes

Available token scopes:

- `servers:read`
- `clients:read`
- `clients:write`
- `materials:read`

## Main Flow

Recommended creation flow:

1. call `GET /api/v1/external/client-targets`
2. choose the topology
3. create the client through `POST /api/v1/external/topologies/{topology_id}/clients`
4. get configs in one of two ways:
   - use `?include_materials=true` and receive materials in the create response
   - or fetch configs separately through `GET /api/v1/external/clients/{client_id}/materials`

If the external system needs connection data immediately, call create with `?include_materials=true`.
If the external system prefers a split flow, create the client first and then call the materials endpoint.

Rules:

- client creation is topology-based, not raw-server-based
- simple topology creates the client on its single VPN node
- proxy topology creates the client on the proxy node
- for proxy topology, `exit_server_id` is optional
- if `exit_server_id` is omitted, the topology `default_exit_server_id` is used

## Endpoints

### `GET /api/v1/external/servers`

Returns known servers and readiness flags.

Example:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/servers
```

### `GET /api/v1/external/client-targets`

Returns topology-aware creation targets.

Response meaning:

- `topology_id`: topology to use for create requests
- `create_server_id`: server where the peer will actually be generated
- `default_exit_server_id`: default preferred exit for proxy topologies
- `exit_servers`: available exits for proxy topologies

Example:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/client-targets
```

Typical response:

```json
[
  {
    "topology_id": 2,
    "topology_name": "ru+multi",
    "topology_type": "proxy-multi-exit",
    "topology_status": "applied",
    "create_server_id": 1,
    "create_server_name": "GORus",
    "create_server_host": "37.140.241.235",
    "default_exit_server_id": 5,
    "exit_servers": [
      {
        "server_id": 5,
        "name": "NdExit",
        "host": "78.17.16.78",
        "priority": 10,
        "is_default": true,
        "status": "healthy",
        "ready_for_managed_clients": true
      }
    ]
  }
]
```

### `GET /api/v1/external/clients`

Returns clients known to the panel.

Query params:

- `archived=true|false`
- `server_id=<id>`
- `service_peer=true|false`

Example:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "https://panel.example.com/api/v1/external/clients?archived=false"
```

### `POST /api/v1/external/topologies/{topology_id}/clients`

Creates a managed client in the selected topology.

Request body fields:

- `name` required
- `include_materials` is an optional query flag, not a JSON field
- `exit_server_id` optional, only for proxy topologies
- `import_note` optional
- `expires_at` optional
- `quiet_hours_start` optional, format `HH:MM`
- `quiet_hours_end` optional, format `HH:MM`
- `quiet_hours_timezone` optional
- `traffic_limit_mb` optional
- `delivery_email` optional
- `delivery_telegram_chat_id` optional
- `delivery_telegram_username` optional

Simple topology example:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"client-001"}' \
  https://panel.example.com/api/v1/external/topologies/1/clients
```

Proxy topology with default exit:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"client-001"}' \
  https://panel.example.com/api/v1/external/topologies/2/clients
```

Proxy topology with explicit exit:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"client-001","exit_server_id":5}' \
  https://panel.example.com/api/v1/external/topologies/2/clients
```

Create and return materials in one response:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"client-001"}' \
  "https://panel.example.com/api/v1/external/topologies/2/clients?include_materials=true"
```

When `include_materials=true`, the response shape is:

```json
{
  "client": {
    "id": 123,
    "name": "client-001",
    "server_id": 1,
    "topology_id": 2,
    "exit_server_id": 5,
    "status": "active"
  },
  "materials": {
    "ubuntu_config": "...",
    "amneziawg_config": "...",
    "amneziavpn_config": "...",
    "qr_png_base64": "...",
    "qr_png_base64_list": ["..."]
  }
}
```

This `materials` object contains the actual connection payloads:

- `ubuntu_config`: plain `.conf` for Ubuntu / AWG
- `amneziawg_config`: plain `.conf` for AmneziaWG
- `amneziavpn_config`: `.vpn` payload for AmneziaVPN
- QR fields: base64 PNG payloads for direct mobile import

Full example:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"client-001",
    "exit_server_id":5,
    "import_note":"created by billing integration",
    "expires_at":"2026-05-01T00:00:00Z",
    "quiet_hours_start":"01:00",
    "quiet_hours_end":"06:00",
    "quiet_hours_timezone":"Europe/Moscow",
    "traffic_limit_mb":10240,
    "delivery_email":"ops@example.com"
  }' \
  https://panel.example.com/api/v1/external/topologies/2/clients
```

### `POST /api/v1/external/clients/{client_id}/suspend`

Manually suspends the client.

Behavior:

- sets `manual_disabled=true`
- sets `status=disabled`
- reapplies panel-managed server config

Example:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/clients/123/suspend
```

### `POST /api/v1/external/clients/{client_id}/resume`

Resumes a manually suspended client.

Behavior:

- sets `manual_disabled=false`
- restores `active` unless a policy restriction still keeps the client disabled
- reapplies panel-managed server config

Example:

```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/clients/123/resume
```

### `GET /api/v1/external/clients/{client_id}/materials`

Returns generated client materials.

Use this endpoint when create was called without `include_materials=true` or when the external system wants to fetch configs separately.

Example:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/clients/123/materials
```

### `DELETE /api/v1/external/clients/{client_id}`

Deletes the client from the panel and reapplies the server config.

Example:

```bash
curl -X DELETE \
  -H "Authorization: Bearer <TOKEN>" \
  https://panel.example.com/api/v1/external/clients/123
```

## Errors

Typical responses:

- `401` missing or invalid token
- `403` external API is disabled
- `404` topology or client not found
- `400` invalid `exit_server_id`
- `400` topology does not have a valid create node
- `400` target server is not ready for managed clients

## Notes

- all create, suspend, resume, materials-read, and delete actions are written to audit logs with actor type `api_token`
- external API works against the same client entities that the panel UI uses
- suspend/resume through external API does not break normal client edits from the panel
