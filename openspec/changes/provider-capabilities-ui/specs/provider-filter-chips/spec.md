## MODIFIED Requirements

### Requirement: Filter chips work in both views
The filter chip row SHALL be present and functional regardless of the active view mode.

#### Scenario: Filter chips above both views
- **WHEN** the Provider Management page is in table view or card view
- **THEN** the filter chips row (All / Active / Inactive / Healthy / Not Configured) SHALL appear above the provider list
- **THEN** selecting a filter chip SHALL correctly filter the displayed providers in both views
