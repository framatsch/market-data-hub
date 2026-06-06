## Why

Die Admin-UI hat mehrere separate Navigationseinträge (Credentials, Schwab Auth, Alerts) die konzeptionell zur Provider-Konfiguration gehören. Das zwingt den Nutzer, zwischen Seiten zu wechseln, um einen einzigen Provider vollständig einzurichten. Die Schwab-Seite ist zudem eine Sackgasse mit manuellem Copy-Paste-OAuth-Flow, obwohl ein automatischer Backend-Callback möglich ist.

## What Changes

- **Entfernt**: Seitenleisteneintrag „Credentials" (eigene Seite) — API Keys werden in Provider Details integriert
- **Entfernt**: Seitenleisteneintrag „Schwab Auth" (eigene Seite) — OAuth-Flow wird in Schwab Provider Details integriert
- **Entfernt**: Seitenleisteneintrag „Alerts" (eigene Seite) — Webhook-Konfiguration wird komplett entfernt; Schwab Token Ablauf wird via Log-File/Grafana überwacht
- **Entfernt**: `AlertsPage.tsx`, `SchwabAuthPage.tsx`, `CredentialsPage.tsx`
- **Neu**: Abstrakte `AuthSection`-Komponenten (3 Varianten):
  - `ApiKeyAuthSection` — editierbare API Key-Liste (für finnhub, polygon, lseg, Schwab)
  - `IbkrConnectionSection` — Host/Port Konfiguration für IBKR Gateway (keine API Keys!)
  - `SchwabOAuthSection` — OAuth-Status + „Re-authorize"-Button mit automatischem Browser-Redirect-Flow
- **Neu**: `ProviderDetails`-Basiskomponente die von allen Providern geteilt wird (Config + Auth in einem)
- **Neu**: `SchwabProviderDetails` erbt `ProviderDetails`, ergänzt um OAuth-spezifische Sektionen
- **Neu**: Chip-Filter auf der `ProvidersPage` (Alle / Aktiv / Inaktiv / Healthy / Nicht konfiguriert)
- **Neu**: Automatischer Schwab OAuth-Callback via Backend-Redirect (`/api/admin/schwab/callback`) — kein manuelles Copy-Paste mehr
- **Geändert**: Navigation: nur noch Dashboard, Providers, Settings
- **Geändert**: `SettingsPage` — behält Default-Provider-Einstellungen, verliert Logo-URL nicht **BREAKING** nur für Alerts-Nutzer die Webhook-URL konfiguriert haben

## Capabilities

### New Capabilities

- `provider-details-ui`: Einheitliche Provider-Details-Komponente mit Config + Auth-Abschnitt, nutzbar von allen Providern; Schwab-Variante erbt und erweitert diese Basis
- `api-key-auth-ui`: Inline API Key Verwaltung innerhalb Provider Details (Liste aller Keys, editierbar, speicherbar)
- `ibkr-connection-ui`: IBKR-spezifische Host/Port Konfiguration im Authentication-Tab (keine API Keys, stattdessen Gateway-Verbindungsparameter)
- `schwab-oauth-auto-flow`: Automatischer OAuth2-Redirect-Flow für Schwab Token Refresh — Backend fängt Callback ab, kein manuelles URL-Copy-Paste
- `provider-filter-chips`: Status-Filter-Chips auf der Provider-Übersicht (Alle / Aktiv / Inaktiv / Healthy / Nicht konfiguriert)

### Modified Capabilities

- `configurable-providers`: Navigation und Edit-Interface ändern sich grundlegend; Credentials wandern in Provider Details

## Impact

- **Frontend**: `admin/src/` — Sidebar, Router, alle Pages außer Dashboard und Settings werden restrukturiert; 3 Seiten entfernt, neue Komponenten unter `components/provider/`
- **Backend**: Neuer Endpoint `GET /api/admin/schwab/callback?code=...&state=...` für automatischen OAuth-Callback; bestehende Schwab-Auth-Endpoints bleiben als Basis
- **Backend**: `DELETE /api/admin/alerts/webhook` oder Endpunkte können entfernt werden (kein UI mehr)
- **Keine DB-Migration**: Credentials-Speicher und Provider-Config bleiben unverändert
