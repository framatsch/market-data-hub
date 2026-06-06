## ADDED Requirements

### Requirement: Provider Status Filter Chips
The `ProvidersPage` SHALL display a row of filter chips above the provider list. The available filter options SHALL be: All, Active, Inactive, Healthy, Not Configured. Multiple chips MAY be selectable simultaneously (additive OR filter). "All" deselects all other chips.

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

#### Scenario: Filter by Not Configured
- **WHEN** the user selects the "Not Configured" chip
- **THEN** only providers whose credentials are all `set: false` SHALL be shown

#### Scenario: Selecting All clears other filters
- **WHEN** any filter is active and the user clicks "All"
- **THEN** all filters SHALL be cleared and all providers SHALL be shown

#### Scenario: No results state
- **WHEN** no providers match the active filter(s)
- **THEN** the system SHALL show a message "No providers match the selected filters"

### Requirement: Filter is Client-Side
The filter SHALL be applied client-side against the data already loaded in the React Query cache. No additional API calls SHALL be made when changing filters.

#### Scenario: Filter does not trigger API call
- **WHEN** the user changes the active filter chip
- **THEN** no new network request SHALL be issued
