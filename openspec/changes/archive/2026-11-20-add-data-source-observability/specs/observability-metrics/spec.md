## MODIFIED Requirements

### Requirement: Low cardinality labels
Every metric SHALL have a fixed label set, and every label SHALL take values only from a predefined, enumerated set; any other value SHALL be mapped to a fallback value of that set. The HTTP request metrics `mdh_http_requests_total` and `mdh_http_request_duration_seconds` SHALL keep the labels `provider`, `endpoint` and `status_class`. The data request metrics SHALL use the labels defined by the `data-source-observability` capability. The realistic number of series of all metrics together SHALL stay below 5,000 per instance; the worst-case budget per metric SHALL be documented in the change that introduces or extends it.

#### Scenario: Provider label values bounded
- **WHEN** metrics are collected
- **THEN** the `provider` label only contains values: ibkr, ibkrweb, lseg, finnhub, polygon, prixe, schwab, alphavantage, financialdatasets, earningsapi, none, and for data request metrics also multiple

#### Scenario: Endpoint label values bounded
- **WHEN** HTTP request metrics are collected
- **THEN** the `endpoint` label only contains values: prices, options, news, companies, health, admin, mcp, metrics, other

#### Scenario: Data endpoint label values bounded
- **WHEN** data request or layer timing metrics are collected
- **THEN** the `endpoint` label only contains the 14 data route keys or `other`

#### Scenario: Status class groups HTTP codes
- **WHEN** responses have status codes 200, 201, 400, 401, 500, 503
- **THEN** status_class label contains only: 2xx, 4xx, 5xx

#### Scenario: Unknown value clamped
- **WHEN** a provider name that is not in the enumerated set is recorded
- **THEN** the metric uses the fallback value `none`
