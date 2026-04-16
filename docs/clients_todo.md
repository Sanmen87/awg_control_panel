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
- Hybrid per-server agent foundation is implemented.
- Server card now shows panel-agent status and manual actions.
- Existing servers can install or reinstall the panel agent from the server card.
- Server runtime metrics now prefer local agent results with SSH fallback.
- Client runtime sync now prefers local agent results with SSH fallback.
- `prepare` / `inspect-standard` now prefer local agent inspect with SSH fallback.
- Agent now supports local-only policy enforcement groundwork:
  - panel syncs `client-policies.json` to the server
  - agent maintains `client-policy-state.json`
  - offline enforcement loop can soft-disable peers locally by policy without panel round-trips
  - panel can later pull local policy state back into DB counters and statuses

### Topologies

- `proxy + 1 exit` flow now uses separate interfaces on proxy:
  - `awg0` for proxy clients
  - `awgN` for proxy-to-exit service links
- Service peer is injected into the exit live config without replacing existing normal exit peers.
- Proxy-side policy routing now uses a dedicated table per exit priority.
- Validation now blocks `proxy + 1 exit` if the chosen exit already has peer `AllowedIPs` overlapping the proxy client subnet.
- Proxy topology editor now exposes proxy routing mode:
  - `all via exit`
  - `selective via exit`
- Selective routing is implemented for:
  - `proxy + 1 exit`
  - `proxy + multi-exit`
- Current selective route source is the static file:
  - `backend/routip/routes.txt`
- Current selective route set covers:
  - Telegram
  - Google
  - Netflix
  - OpenAI
  - Twitter/X
  - Discord
- Selective runtime on proxy now manages:
  - `ipset`
  - `iptables mangle` marking
  - per-exit routing tables
- Proxy failover agent is now selective-aware:
  - it no longer reintroduces conflicting source-based `ip rule`
  - it restarts cleanly on reinstall
  - in `multi-exit` it can rebuild default selective path for the active exit

### UI

- Sidebar visually split into separate sections.
- `Dashboard` label replaces `Home`.
- `Delivery methods` label replaces `Integrations`.
- `Web / HTTPS` moved into its own sidebar page.
- Logout moved out of sidebar into the content topbar.
- Topology helper copy now reflects current reality:
  - only one compatible AWG profile is exposed
  - full profile switching waits for Amnezia 2.0 protocol support
  - selective-routing helper now describes the current static route list

### Backups

- `full bundle` is now the main backup format.
- Bundle backup includes:
  - panel PostgreSQL dump
  - server runtime/config snapshots when available
  - unified `manifest.json`
- Backup storage path is configured through `BACKUP_STORAGE_PATH`.
- Automatic backup retention and cleanup are supported.
- Uploaded bundles are handled separately in the UI.
- Manual bundle-oriented restore flow is available for:
  - panel restore
  - selected server restore
- dedicated `/backups` route exists in the UI

### Web / HTTPS

- Separate `Web / HTTPS` page in the sidebar.
- Web settings storage:
  - public domain
  - Let's Encrypt email
  - HTTP / HTTPS mode
- Web diagnostics in UI:
  - DNS
  - port `80`
  - port `443`
  - TLS certificate state and expiry
- nginx config preview in UI
- Apply action now:
  - writes runtime nginx config
  - reloads nginx
  - requests or renews Let's Encrypt certificate in `HTTPS` mode
- HTTP requests sent to server IP or unknown host are redirected to the configured canonical domain
- Panel web exposure is now a first-class path, no longer just a side setting under delivery/integrations

### External API

- External API is exposed as a dedicated service-token integration surface.
- Web / HTTPS page can enable or disable `/api/v1/external/*`.
- Web / HTTPS page can generate or rotate the default external API token.
- Admin-issued scoped API tokens are supported through `/api/v1/api-tokens`.
- Topology-aware external client targets are available.
- External managed client creation now works only by topology:
  - simple topology
  - proxy + exit topology
- Proxy topology create automatically uses the proxy node as the real create server.
- Proxy topology create supports default-exit selection when `exit_server_id` is omitted.
- External API can return configs in the create response with `?include_materials=true`.
- External API can also fetch configs separately through the materials endpoint.
- External API supports client suspend, resume, delete, and generated-material read actions.
- External API actions are written to audit logs with actor type `api_token`.
- `docs/externalapi.md` contains the usage guide and examples.

### Security

- Built-in anti-bruteforce login guard backed by Redis.
- Temporary ban after repeated failed logins.
- Counters keyed by:
  - source IP
  - username
- Security events are written into `audit_logs`:
  - `auth_login_failed`
  - `auth_login_banned`
  - `auth_login_blocked`

### Extra Services

- Separate main-menu section: `Extra services`.
- Eligible install targets:
  - exit nodes of proxy topologies
  - standalone standard servers
- Implemented services:
  - `MTProxy`
  - `SOCKS5`
  - `Xray / VLESS + Reality`
- `MTProxy` practical mode:
  - `telegrammessenger/proxy`
  - Fake TLS `ee...` secret
  - short domain up to 15 bytes
  - install / refresh status / delete from server / email delivery
- `SOCKS5`:
  - docker-based install
  - generated username / password
  - refresh status / delete from server / email delivery
- `Xray / VLESS + Reality`:
  - docker-based install
  - generated `UUID`, `shortId`, and `x25519` keypair
  - ready-to-import `vless://` client link
  - currently validated as a practical iPhone-friendly path
- Install UI for extra services is now card-based with:
  - aligned install actions
  - shared card layout
  - copy-to-clipboard in MTProxy and Xray connection blocks

## In Progress

### Notifications

- Notification levels are defined in UI and settings storage.
- Automatic event generation for each level is not fully implemented yet.
- Current live automatic behavior is still limited compared with the target notification model.

### Delivery UX

- Email template is implemented, but still needs real-client visual review across mail providers.
- Telegram delivery is operational, but still not as polished as the email package.

### Web Runtime

- Current public VPS frontend runtime now uses the production `runner` target instead of `next dev`.
- Frontend production runtime is hardened enough for the current MVP deployment:
  - no bind-mounted frontend source tree
  - no persisted frontend `.next` runtime volume
  - non-root `nextjs` runtime user
  - read-only root filesystem
  - `/tmp` mounted as `tmpfs` with `noexec`
  - `cap_drop: ALL`
  - `no-new-privileges`
- Local frontend development mode remains available:
  - `dev` target no longer copies the full frontend source tree into the image
  - `frontend/.dockerignore` now limits noisy build context
  - bind-mounted `./frontend:/app` keeps hot reload
- Log rotation is enabled in compose.
- Remaining work here is backend/runtime hardening, not emergency disk-growth mitigation.

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
- Add dynamic route-list generation and refresh for selective routing instead of the current static `backend/routip/routes.txt`.
- Add UI/state for advanced selective categories and future BGP-fed route groups.

### Per-Server Agent

- Finish moving remaining read-only SSH checks to agent handlers where safe.
- Decide which write paths may later move to agent and which must stay SSH-only.
- Add clearer agent status / task history UI in the server card or dedicated page.
- Formalize the agent mode switch:
  - without a public agent-facing panel page, agent works through local files and SSH-driven exchange
  - with a public agent-facing panel page, the same agent switches to API sync mode
- Define the first web-agent contract:
  - status heartbeat
  - result upload
  - allowlisted task fetch
  - authenticated panel-to-agent and agent-to-panel flow
- Add explicit agent-side policy event journal and surface it in the UI.
- Add conflict-resolution rules for offline-collected counters and server-side task results.
- Harden and validate offline client-policy enforcement:
  - rolling traffic limits
  - `expires_at`
  - quiet hours
  - reconnect sync back into panel state
- Decide whether selective route-list refresh should later move into the agent for local reconcile.

### Security UI

- Add dedicated frontend page for `audit_logs`.
- Add filters for brute-force events:
  - failed logins
  - bans
  - blocked retries
- Add optional whitelist for trusted admin IPs.
- Decide whether brute-force thresholds should be editable from panel settings.

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

- Implement per-peer bandwidth limits through agent-managed `tc` shaping.
- Use client `assigned_ip` as the stable shaping match key.
- Keep shaping logic agent-side and reconcile-based, not ad-hoc shell from panel.
- Decide exact scope for v1:
  - single symmetric limit
  - or separate RX / TX limits
- Confirm whether shaping must be applied:
  - inside `amnezia-awg`
  - or on the host namespace
- Add UI controls for speed policy in the client settings modal.

### Web Runtime And Hardening

- Keep public VPS frontend on production `runner` mode and do not expose `next dev`.
- Replace backend `uvicorn --reload` with a production backend process profile.
- Harden current `Web / HTTPS` apply flow and error reporting.
- Support a practical "panel on proxy server" deployment profile without breaking AWG routing.
- Add host-level brute-force protection:
  - `fail2ban` integration or equivalent
  - parsing of `nginx` / auth-related logs
- Consider optional hardening modes:
  - localhost-only admin mode
  - public web mode
  - restricted web mode with IP allowlist

### API And Integrations

- Expand REST API for external service-token integrations.
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
