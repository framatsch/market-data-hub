## Context

The provider overview table (added in `provider-ui-consolidation`) shows: expand arrow, provider name, status chip, enabled toggle. There is no indication of what each provider can do. The backend `_provider_status()` helper in `routes_admin.py` builds the response dict — currently it does not include capabilities.

`ProviderCapabilities` interface exists in `admin/src/types.ts` (lines 62–67) but is not connected to `Provider` and not used anywhere. It will be replaced by a simple `capabilities: string[]` on `Provider`.

## Goals / Non-Goals

**Goals:**
- `GET /api/admin/providers` response includes `capabilities: list[str]` per provider
- Provider table: new **"Capabilities"** column with MUI Chips (one per capability)
- Provider name cell: subtitle line in secondary typography (`Prices · Options · Companies` etc.)
- Filter chips row: verified working with the table
- `Provider` TypeScript type: `capabilities?: string[]` added

**Non-Goals:**
- Card grid view / view switcher
- Capability-based filtering (filter chips filter by status, not by capability)
- Capability editing (capabilities are derived from code, not user-configurable)
- Changing the detail panel layout

## Decisions

### D1: Capabilities derived at runtime via `isinstance` — not configured

In `_provider_status()`, the provider instance is available (line 257: `provider = registry.get_provider_instance(name)`). Four `isinstance` checks against the four base classes produce the list. Order: `["prices", "options", "companies", "news"]` — consistent everywhere.

```python
caps = []
if isinstance(provider, BasePriceProvider): caps.append("prices")
if isinstance(provider, BaseOptionsProvider): caps.append("options")
if isinstance(provider, BaseCompanyProvider): caps.append("companies")
if isinstance(provider, BaseNewsProvider): caps.append("news")
```

For a disabled or unavailable provider (no instance), capabilities are derived from the class itself: `isinstance(cls, ...)` checks on the class — or a static lookup dict as a simpler alternative.

### D2: Static fallback capability map for unloaded providers

When `provider is None` (not loaded — e.g. `schwab-py` not installed, or provider disabled at startup), the instance check cannot run. A static dict `PROVIDER_CAPABILITIES` in `routes_admin.py` maps provider name → capabilities list. This is the fallback when the instance is unavailable.

```python
PROVIDER_CAPABILITIES: dict[str, list[str]] = {
    "ibkr":    ["prices", "options", "companies"],
    "lseg":    ["prices", "companies"],
    "schwab":  ["prices", "options"],
    "finnhub": ["news"],
    "polygon": ["prices", "companies"],
    "mock":    ["news"],
    "prixe":   ["prices"],
}
```

### D3: Filter chips — no change to logic, verify only

The `filterProviders` function and `activeFilters` state are already correct. Verify the `Stack` of filter chips remains rendered above the `TableContainer`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Static `PROVIDER_CAPABILITIES` dict goes stale when providers gain new capabilities | The dict is also used as fallback documentation — adding a lint/test that compares dict to actual `isinstance` results for loaded providers |
| `ProviderCapabilities` interface removal may break something | Search confirms it is defined but never imported — safe to remove |
