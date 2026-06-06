## ADDED Requirements

### Requirement: Provider Status Filter Chips
The `ProvidersPage` SHALL display a row of filter chips above the provider list. The available filter options SHALL be: All, Active, Inactive, Healthy, Not Configured. Multiple chips MAY be selectable simultaneously (additive OR filter: a provider matches if it satisfies ANY selected filter). "All" deselects all other chips.

#### Scenario: Default state
- **WHEN** the Providers page loads
- **THEN** the "All" chip SHALL be selected and all providers SHALL be shown

#### Scenario: Filter by Active
- **WHEN** the user selects the "Active" chip
- **THEN** only providers with `enabled: true` SHALL be shown

#### Scenario: Filter by Inactive
- **WHEN** the user selects the "Inactive" chip
- **THEN** only providers with `enabled: false` SHALL be shown

#### Scenario: Filter by Healthy
- **WHEN** the user selects the "Healthy" chip
- **THEN** only providers with `status: "healthy"` SHALL be shown

#### Scenario: Filter by Not Configured — API key providers
- **WHEN** the user selects the "Not Configured" chip
- **AND** a provider is finnhub, polygon, lseg, or schwab
- **THEN** that provider SHALL be included if ALL of its credentials have `set: false` in `GET /api/admin/credentials`

#### Scenario: Filter by Not Configured — IBKR
- **WHEN** the user selects the "Not Configured" chip
- **AND** the provider is IBKR
- **THEN** IBKR SHALL be included if `connection_config.account_id === "DU123456"` (the placeholder default)
- **NOTE**: host `127.0.0.1` and port `4001` are valid defaults for a local Gateway setup and SHALL NOT be used as "not configured" signals

#### Scenario: Filter by Not Configured — mock and prixe
- **WHEN** the user selects the "Not Configured" chip
- **THEN** mock and prixe providers SHALL NEVER match this filter (they have no configurable credentials)

#### Scenario: Selecting All clears other filters
- **WHEN** any filter is active and the user clicks "All"
- **THEN** all filters SHALL be cleared and all providers SHALL be shown

#### Scenario: No chips selected behaves as All
- **WHEN** no chip is selected (e.g. user deselects the last active chip)
- **THEN** all providers SHALL be shown (equivalent to "All")

#### Scenario: Mutually exhaustive combination
- **WHEN** both "Active" and "Inactive" chips are selected simultaneously
- **THEN** all providers SHALL be shown (the combination is functionally equivalent to "All")

#### Scenario: No results state
- **WHEN** no providers match the active filter(s)
- **THEN** the system SHALL show a message "No providers match the selected filters"

### Requirement: Filter is Client-Side
The filter SHALL be applied client-side against the data already loaded in the React Query cache. No additional API calls SHALL be made when changing filters.

#### Scenario: Filter does not trigger API call
- **WHEN** the user changes the active filter chip
- **THEN** no new network request SHALL be issued
