## Why

The provider overview table shows name, status, and enabled toggle — but nothing about what a provider actually does. A user setting up the system for the first time has no way to know from the UI that IBKR supports prices + options + companies while Finnhub only supports news, without reading external documentation. This creates friction during initial setup, especially combined with the new "all disabled by default" behaviour.

## What Changes

- **Backend** — `GET /api/admin/providers` response includes a new `capabilities: list[str]` field per provider. Values are a subset of `["prices", "options", "companies", "news"]`, determined at runtime by `isinstance` checks against the four base classes.
- **Frontend** — Provider table gains a **"Capabilities"** column showing small MUI Chips per capability (`Prices`, `Options`, `Companies`, `News`) in the overview row
- **Frontend** — Provider name cell gains a subtle **subtitle** (secondary typography) listing capabilities as a dot-separated string for quick scanning without opening details
- **`Provider` TypeScript interface** — `capabilities?: string[]` field added
- **`ProviderCapabilities` interface** in `types.ts` already exists but unused — it will be removed in favour of the simpler `capabilities: string[]` on `Provider`

## Capabilities

### New Capabilities

- `provider-capabilities-display`: Backend exposes and frontend renders the service types each provider supports (prices / options / companies / news)

### Modified Capabilities

- `provider-filter-chips`: Filter chip row verified working with the table
- `configurable-providers`: Provider list now communicates capability context to the user during setup

## Impact

- **`app/api/routes_admin.py`**: `_provider_status()` helper extended to include `capabilities` list
- **`admin/src/types.ts`**: `Provider` interface gains `capabilities?: string[]`; `ProviderCapabilities` interface removed
- **`admin/src/pages/ProvidersPage.tsx`**: capabilities column added to table
- **`admin/src/components/provider/ProviderDetailsPanel.tsx`**: no changes needed
- **No DB migration, no new endpoints**
