## ADDED Requirements

### Requirement: Initial provider state on first start
On first deployment (no existing DB), all non-mock providers SHALL start as disabled. The user enables providers explicitly via the admin UI.

#### Scenario: Fresh installation — providers disabled
- **WHEN** the application starts with an empty `keys.db`
- **THEN** all providers except `mock` SHALL have `enabled=False` in `ProviderRuntimeConfig`
- **THEN** `default_news_provider` SHALL be `None` in system settings
- **THEN** `default_price_provider`, `default_options_provider`, `default_company_provider` SHALL be `None`

#### Scenario: Existing installation — no change
- **WHEN** the application starts with an existing `keys.db` containing configured provider rows
- **THEN** existing rows SHALL NOT be overwritten
