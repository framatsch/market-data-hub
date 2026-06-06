## Context

Die Admin-UI hat 6 Navigationseinträge: Dashboard, Providers, Credentials, Schwab Auth, Alerts, Settings. Credentials, Schwab Auth und Alerts sind konzeptionell Unteraspekte der Provider-Konfiguration, aber als eigenständige Seiten modelliert. Das führt zu kognitiver Fragmentierung: Um Schwab vollständig einzurichten, wechselt man zwischen 3 Seiten.

Das Frontend ist React 19 + TypeScript + MUI v9. Komponenten sind ausschließlich funktional (keine Klassen). „Vererbung" wird in React durch Komposition + gemeinsame Interfaces gelöst. Das Backend läuft als FastAPI mit bestehenden Endpoints für Provider-Config, Credentials, Schwab OAuth.

Der aktuelle Schwab OAuth-Flow ist manuell: User kopiert eine URL, öffnet sie, kopiert den Redirect-URL, fügt ihn ein. Ein automatischer Backend-Callback ist technisch möglich, weil Schwab `http://localhost` als `redirect_uri` erlaubt.

## Goals / Non-Goals

**Goals:**

- Navigation auf 3 Einträge reduzieren: Dashboard, Providers, Settings
- Provider Details Page: Config + Auth-Konfiguration in einer einzigen expandierten Ansicht
- Einheitliche `ProviderDetailsPanel`-Basiskomponente, geteilt von allen Providern
- Drei Auth-Section-Komponenten, je nach Provider-Typ:
  - `ApiKeyAuthSection` — editierbare Key-Liste (für finnhub, polygon, lseg, Schwab)
  - `IbkrConnectionSection` — Host/Port Felder für IBKR Gateway
  - `SchwabOAuthSection` — OAuth-Status + automatischer Re-authorize-Flow (Schwab, zusätzlich zu ApiKeyAuthSection)
- Chip-Filter auf der Provider-Übersicht
- Schwab OAuth automatisch: Backend-Redirect, kein Copy-Paste
- Alerts/Webhook komplett entfernen (Log-basiertes Monitoring via Grafana)

**Non-Goals:**

- Kein Umbau des Backend-Credential-Speichers oder Provider-Registry
- Kein Dark Mode, kein Theming-Umbau
- Keine zusätzlichen OAuth-Provider (nur Schwab)
- Kein Umbau der Dashboard-Seite
- Keine Änderung an bestehenden API-Endpoints außer neuem Schwab-Callback-Endpoint

## Decisions

### D1: Komposition statt Klassen-Vererbung

**React ist funktional** — keine Klassenkomponenten. „Vererbung" wird modelliert als:

```
ProviderDetailsPanel (Basiskomponente)
├── Props: provider, config, authSection: ReactNode
└── Rendert: Header | ConfigSection | AuthSection (über authSection-Slot)

ApiKeyAuthSection          ← finnhub, polygon, lseg, Schwab (API Keys)
IbkrConnectionSection      ← IBKR (Host, Port — keine API Keys!)
SchwabOAuthSection         ← Schwab (zusätzlich zu ApiKeyAuthSection)
```

`ProvidersPage` entscheidet mittels lookup:
- `schwab` → authSection enthält `ApiKeyAuthSection` + `SchwabOAuthSection` (gestapelt)
- `ibkr` → authSection = `<IbkrConnectionSection />`
- alle anderen (finnhub, polygon, lseg) → authSection = `<ApiKeyAuthSection providerName={provider.name} />`

Keine eigene Router-Route pro Provider — alles bleibt in der Accordion-Struktur der `ProvidersPage`.

**Alternativen verworfen:**
- Separate Route `/admin/providers/:name` — zu komplex für die aktuelle Datenmenge (4-5 Provider), Accordion ist UX-gerechter
- Klassen-Vererbung via abstract TypeScript-Klassen — unidiomatic in React, bricht Hooks-Regeln

---

### D2: Auth-Konfiguration in Accordion-Details, nicht in Modal

Die Provider-Details (Accordion) bekommen **Tabs** oder **Sektions-Divider**:

```
[Provider Name ▾]
  ┌─ Enabled / Status Chip ─────────────────────────────┐
  │  Tab: Configuration | Tab: Authentication            │
  │                                                       │
  │  [Configuration Tab]                                  │
  │  Timeout, Retry, Circuit Breaker, Connection JSON     │
  │                                                       │
  │  [Authentication Tab]                                 │
  │  API Key Auth:  [key1] [key2] [+ Add]  [Save]        │
  │  Schwab OAuth:  Status: ACTIVE (3d)  [Re-authorize]  │
  └───────────────────────────────────────────────────────┘
```

MUI `Tabs` innerhalb `AccordionDetails` — sauber, keine Route-Komplexität.

**Alternativen verworfen:**
- Separate Route pro Provider — Overengineering für 4-5 Provider
- Alle Felder ohne Tabs — AccordionDetails würde zu lang

---

### D3: Schwab OAuth — Automatischer Backend-Callback

**Flow:**
1. User klickt „Re-authorize" in `SchwabOAuthSection`
2. Frontend ruft `GET /api/admin/schwab/auth/url` → erhält `auth_url`
3. Frontend öffnet `auth_url` in neuem Tab: `window.open(auth_url)`
4. Schwab leitet nach Login zu `http://localhost:8000/api/admin/schwab/callback?code=...&state=...`
5. Backend tauscht Code gegen Token, speichert Token, setzt Schwab-Status auf aktiv
6. Backend antwortet mit `200 + HTML-Seite` ("Authorization successful, you can close this tab") oder leitet zu `/admin` weiter
7. Ursprüngliches Tab: `SchwabOAuthSection` pollt `GET /api/admin/schwab/auth/status` alle 2s für max 60s bis Status = `active`
8. Bei Erfolg: Snackbar „Schwab successfully re-authorized", Stop polling

Neuer Backend-Endpoint: `GET /api/admin/schwab/callback` — übernimmt `code` + `state` Query-Params, tauscht Token, returnt HTML oder Redirect.

**Warum Polling statt WebSocket:** Einfacher zu implementieren, 60s max ist akzeptabel für einmaligen Vorgang.

**Alternativen verworfen:**
- Manuelles Copy-Paste (bisherig) — schlechte UX
- PostMessage von Popup zu Parent — zu komplex, Cross-Origin-Probleme möglich

---

### D4: Provider-Filter als Zustandsfilter im Client

Filter-Chips werden **client-seitig** gegen die geladene Provider-Liste angewendet:

```
[Alle]  [Aktiv]  [Inaktiv]  [Healthy]  [Nicht konfiguriert]
```

`Nicht konfiguriert` = Provider ist enabled, hat aber seine erforderliche Konfiguration nicht gesetzt:
- Für finnhub, polygon, lseg, schwab: credentials alle `set: false`
- Für ibkr: `connection_config.host` und `connection_config.port` sind leer/Defaults (127.0.0.1:4001 unverändert)
- Provider ohne config-Bedarf (mock, prixe) gelten immer als konfiguriert

Der Filter ist ein `Set<string>` im lokalen State. Kein API-Parameter, kein Refetch.

---

### D5: Webhook/Alerts entfernen

`AlertsPage.tsx` und alle zugehörigen Backend-Endpoints (`/api/admin/alerts/*`) werden entfernt. Schwab Token Ablauf-Warnungen werden über strukturiertes Logging (bereits vorhanden) an Grafana delegiert. Kein Ersatz in der UI.

**Alternativen verworfen:**
- Webhook in Settings verschieben — Komplexität ohne klaren Nutzen, Grafana-Integration ist robuster

---

### D6: Credentials API-Format bleibt unverändert

Die API `GET /api/admin/credentials`, `PUT /api/admin/credentials/{provider}` wird unverändert konsumiert. IBKR hat KEINE Einträge in `CREDENTIAL_ALLOWLIST` (siehe `routes_admin.py`), stattdessen wird IBKR über `connection_config` im Provider config Objekt konfiguriert, mit dediziertem Endpoint `PUT /api/admin/providers/ibkr/gateway`. Das Frontend muss diese Unterscheidung abbilden: für IBKR wird `IbkrConnectionSection` gerendert (liest/schreibt `connection_config`), für alle anderen die `ApiKeyAuthSection` (liest/schreibt `PUT /api/admin/credentials/{provider}`).

### D7: IBKR Datenquelle im Frontend

`IbkrConnectionSection` liest die Felder `host` und `port` aus `connection_config` von `GET /api/admin/providers/ibkr/config` und schreibt via `PUT /api/admin/providers/ibkr/gateway`. Das ist konsistent mit dem bestehenden Backend.

Bei allen anderen Providern (finnhub, polygon, lseg, schwab) wird `ApiKeyAuthSection` gerendert, die auf dem `GET /api/admin/credentials`-Cache basiert.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Schwab OAuth Callback schlägt fehl (Netzwerk, Code expired) | Fallback: Error-State in `SchwabOAuthSection` mit „Try again"-Button; Polling-Timeout nach 60s mit klarer Fehlermeldung |
| `redirect_uri` in Schwab Developer App muss auf `http://localhost:8000/api/admin/schwab/callback` gesetzt sein | Dokumentation in Settings-Seite als Info-Text; Backend gibt hilfreiches Error wenn redirect_uri falsch |
| Nutzer hatte Webhook-URL konfiguriert — nach Update weg | **Breaking Change** für Alert-Nutzer, aber explizit gewünscht; ggf. Backend-Endpoint bleibt noch eine Version erhalten |
| Accordion mit Tabs kann bei vielen Feldern tief werden | MUI Tabs sind standardmäßig scrollbar; AccordionDetails hat max-height mit overflow |
| Polling (Schritt 7) kann unnötig lange laufen | Polling stoppt nach 60s mit Timeout-Meldung; User kann manuell refreshen |

## Migration Plan

1. Neue Komponenten parallel zu bestehenden bauen
2. Router: neue Routen aktivieren, alte deaktivieren
3. Sidebar: neue Einträge, alte entfernen
4. Backend: neuen Schwab-Callback-Endpoint hinzufügen
5. Backend: Alerts-Endpoints optional deprecaten (nicht sofort löschen, um Rollback zu ermöglichen)
6. Tests: E2E für Provider-Details-Tabs und Schwab OAuth-Flow

## Open Questions

- Soll `SchwabOAuthSection` die `days_remaining`-Information aus dem Dashboard-Context ziehen (um doppelte Requests zu vermeiden) oder eigenständig pollen? → Empfehlung: eigener `useQuery`-Hook mit shared query key `['schwab-status']` sodass React Query den Cache teilt.
- Soll die Schwab-Callback-Seite nach erfolgreichem Token-Tausch zu `/admin` weiterleiten oder ein eigenständiges HTML-"Schließen"-Overlay zeigen? → Empfehlung: Redirect zu `/admin?schwab=authorized` damit das Provider-Panel automatisch auf Schwab springt und Erfolg zeigt.
