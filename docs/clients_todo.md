# AWG Control Panel Status

## Done

### Clients

- Redesigned `Clients` table with icon-driven statuses and actions.
- Click on a client row opens a modal with materials instead of using a separate button.
- Separate materials for:
  - `Ubuntu / AWG`
  - `AmneziaWG`
  - `AmneziaVPN`
- Separate QR flows for:
  - `AmneziaWG`
  - `AmneziaVPN`
- Config downloads from the client modal:
  - `.conf`
  - `.vpn`
- Inline delivery flow from the client modal.
- Delivery contacts stored per client:
  - email
  - Telegram chat id
  - Telegram username
- Traffic limit, quiet hours, and expiration controls in the client settings modal.
- Rolling 30-day traffic accounting based on `awg/wg show all dump`.
- Manual disable separated from policy disable.
- Archived clients flow:
  - deleting a server archives linked clients
  - archived clients are hidden from the default list
  - archive view is available in the UI
  - archived clients are ignored by worker/Celery sync
  - re-import restores archived clients by `public_key`

### Delivery And Notifications

- Email delivery of client config package.
- Telegram delivery of client config package.
- Rich email template with:
  - bilingual RU / EN content
  - quick start block
  - inline QR for `AmneziaWG` and `AmneziaVPN`
  - attached config files
  - platform download links
- Telegram delivery now includes:
  - quick start text
  - QR images
  - config files
- Delivery settings page split into visual modules:
  - notifications
  - email
  - Telegram
- Test buttons for:
  - email delivery
  - Telegram delivery
- Multiple admin email targets supported from a single field:
  - comma-separated
  - one address per line
- Notification level selector updated to logical levels:
  - `disabled`
  - `important_only`
  - `access_changes`
  - `policy_and_expiry`
  - `full_monitoring`

### Servers And Runtime

- Dashboard server runtime block with:
  - CPU
  - RAM
  - disk
  - network
  - uptime
  - load
  - container status
- Top peers by traffic on dashboard.
- API status and client-access overview on dashboard.
- Runtime sync via Celery periodic tasks.
- Install-method split aligned around:
  - `docker`
  - `go`
  - `custom`
- `runtime_flavor` support in server model and UI.
- Bootstrap now re-inspects live AWG runtime automatically after install.
- Managed-clients server picker now excludes `exit` nodes from `proxy + 1 exit` topologies.

### Topologies

- `proxy + 1 exit` flow now uses separate interfaces on proxy:
  - `awg0` for proxy clients
  - `awgN` for proxy-to-exit service links
- Service peer is injected into the exit live config without replacing existing normal exit peers.
- Proxy-side policy routing now uses a dedicated table per exit priority.
- Validation now blocks `proxy + 1 exit` if the chosen exit already has peer `AllowedIPs` overlapping the proxy client subnet.

### UI

- Sidebar visually split into separate sections.
- `Dashboard` label replaces `Home`.
- `Delivery methods` label replaces `Integrations`.
- Logout moved out of sidebar into the content topbar.

## In Progress

### Notifications

- Notification levels are defined in UI and settings storage.
- Automatic event generation for each level is not fully implemented yet.
- Current live automatic behavior is still limited compared with the target notification model.

### Delivery UX

- Email template is implemented, but still needs real-client visual review across mail providers.
- Telegram delivery is operational, but still not as polished as the email package.

## Next

### Notification Engine

- Implement actual automatic notifications for `important_only`:
  - server unavailable
  - deploy or sync failed
  - backup failed
  - client disabled by traffic limit
  - client expired
- Implement automatic notifications for `access_changes`:
  - client created
  - client reissued
  - client archived
  - manual enable or disable
  - config delivery event
- Implement automatic notifications for `policy_and_expiry`:
  - quiet hours activated
  - quiet hours released
  - expiry warning
  - 80/90/100% traffic threshold warnings

### Delivery Polish

- Add a delivery / notification event log page in the UI.
- Add email template preview in the admin UI.
- Add optional preview endpoint for HTML email debugging.
- Improve Telegram delivery layout and message grouping.
- Decide whether Telegram username should remain editable if actual delivery is performed by `chat_id`.

### Clients And Materials

- Finish validation of the redesigned clients page after frontend dependencies are restored and `next build` becomes available.
- Tighten table spacing and responsive behavior after real browser review.
- Review imported-peer messaging and visual differentiation.
- Add keyboard accessibility for opening and closing client modals.
- Add explicit UI messaging when a topology server is hidden from managed-client creation because it is an `exit` node.
- Revisit extended AWG profile presets after mobile clients support the Amnezia 2.0 format:
  - return `balanced` and `aggressive` to the topology UI only after verified mobile compatibility
  - keep `compatible` as the only exposed preset until then

### Proxy + Exit Hardening

- Ensure proxy-side stale `MASQUERADE` rules are always removed during topology re-apply, including old manual or legacy leftovers.
- Add an automatic cleanup/migration path for existing broken `proxy + 1 exit` deployments where service peer was previously written into proxy `awg0`.
- Add end-to-end verification that a managed client created on proxy really exits with the selected exit node public IP.

## Later

### Server Install Defects

- Fix install-method drift during bootstrap:
  - if the user selects `docker` for a new server, the onboarding pipeline must not silently finish with detected `go`
  - current defect: a server added with `docker` selected can end up installed/detected as `go-userspace`
  - expected behavior:
    - either enforce the selected install method
    - or stop with a clear error/status instead of silently switching runtime type
  - priority: tertiary / low, but must be fixed before the install wizard is considered reliable

### Speed Limits

- Implement per-peer bandwidth limits for docker-installed AWG servers.
- Confirm whether shaping must be applied:
  - inside `amnezia-awg`
  - or on the host namespace
- Build a reconcile-based speed-policy service instead of ad-hoc shell commands.
- Use client `assigned_ip` as the stable shaping match key.
- Add UI controls for speed policy in the client settings modal.

### Backups

- Implement full backups of AWG server state:
  - `wg0.conf`
  - `clientsTable`
  - peers
  - live config metadata
- Implement panel backups:
  - PostgreSQL
  - generated client materials
  - backup storage inventory
- Add restore workflows for:
  - panel restore
  - server restore
  - fast redeploy / disaster recovery

### Web Exposure And Hardening

- Add a simple production web mode so the panel can be published quickly on the same server that hosts the proxy.
- Provide a standard deployment path with:
  - `nginx`
  - TLS
  - reverse proxy for `frontend` and `backend`
- Support a practical "panel on proxy server" deployment profile without breaking AWG routing.
- Add login protection in the app layer:
  - rate limiting for auth endpoints
  - temporary lockout / backoff after repeated failed logins
  - audit trail for failed and successful admin logins
- Add host-level brute-force protection:
  - `fail2ban` integration or equivalent
  - parsing of `nginx` / auth-related logs
- Consider optional hardening modes:
  - localhost-only admin mode
  - public web mode
  - restricted web mode with IP allowlist

### API And Integrations

- Expand REST API for external JWT-authenticated integrations.
- Support automated client creation and issuance outside the web UI.
- Support integration scenarios such as:
  - HR onboarding / offboarding
  - service desk tooling
  - scripted provisioning

## Ops

- Rebuild and restart services after backend or frontend changes:

```bash
sudo docker compose build backend worker scheduler frontend
sudo docker compose up -d backend worker scheduler frontend nginx
```

- If runtime data does not refresh:
  - check `scheduler`
  - check `worker`
  - check Alembic migrations
