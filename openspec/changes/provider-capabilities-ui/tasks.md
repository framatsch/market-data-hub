## 1. Backend — Capabilities Field

- [ ] 1.1 In `app/api/routes_admin.py`, add static dict `PROVIDER_CAPABILITIES: dict[str, list[str]]` mapping each known provider name to its capability list (used as fallback when provider instance is unavailable): `ibkr→[prices,options,companies]`, `lseg→[prices,companies]`, `schwab→[prices,options]`, `finnhub→[news]`, `polygon→[prices,companies]`, `mock→[news]`, `prixe→[prices]`
- [ ] 1.2 In `_provider_status()` helper: add `capabilities` field to the returned dict — derived from `isinstance` checks on the loaded provider instance; fall back to `PROVIDER_CAPABILITIES.get(name, [])` when instance is `None`
- [ ] 1.3 Add imports: `BasePriceProvider`, `BaseOptionsProvider`, `BaseCompanyProvider`, `BaseNewsProvider` from `app/providers/base` (may already be imported — verify)
- [ ] 1.4 Verify the `Provider` response schema (Pydantic model or TypedDict if any) includes `capabilities: list[str]`; if it is a plain `dict` return, no schema change needed

## 2. Frontend — TypeScript Types

- [ ] 2.1 In `admin/src/types.ts`: add `capabilities?: string[]` to the `Provider` interface
- [ ] 2.2 Remove the now-unused `ProviderCapabilities` interface (lines 62–67) — verify it is not imported anywhere before deleting

## 3. Frontend — Capabilities in Table View

- [ ] 3.1 In `admin/src/pages/ProvidersPage.tsx`, add a **"Capabilities"** column to the `TableHead` row
- [ ] 3.2 In the provider `TableRow`: add a `TableCell` that renders `provider.capabilities?.map(cap => <Chip key={cap} label={cap} size="small" variant="outlined" />)` wrapped in a `Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}`
- [ ] 3.3 In the provider name `TableCell`: add a subtitle line below the bold name — `<Typography variant="caption" color="text.secondary">{provider.capabilities?.join(' · ')}</Typography>`
- [ ] 3.4 Ensure `capabilities` is not `undefined` before rendering — use optional chaining and default to `[]`

## 4. Frontend — Filter Chips Verification

- [ ] 4.1 Verify filter chips `Stack` is rendered above the `TableContainer`
- [ ] 4.2 Verify `toggleFilter` and `activeFilters` state correctly filter `filteredProviders`
- [ ] 4.3 Verify "No providers match the selected filters" empty state is shown

## 5. TypeScript Build & Verification

- [ ] 5.1 Run `npx tsc --noEmit` in `admin/` — zero errors
- [ ] 5.2 Run `uv run ruff check app/` — no backend lint errors
- [ ] 5.3 Manual smoke: Provider Management page loads; each provider row shows correct capability chips; IBKR shows Prices + Options + Companies; Mock shows News only
- [ ] 5.4 Manual smoke: filter chips filter correctly
