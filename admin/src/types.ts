export interface Provider {
  name: string;
  enabled: boolean;
  status: 'healthy' | 'paused' | 'degraded' | 'offline' | 'disabled' | 'unavailable';
  error?: string | null;
  capabilities?: string[];
  price_support?: {
    price_sec_types: string[];
    price_history_sec_types: string[];
    native_intervals?: string[];
    derived_intervals?: string[];
  } | null;
  options_support?: {
    option_underlying_sec_types: string[];
  } | null;
  volatility_support?: {
    volatility_sec_types: string[];
    volatility_history_sec_types: string[];
    volatility_tenors: number[];
  } | null;
  config_summary?: {
    timeout_seconds: number;
    retry_count: number;
    rate_limit_per_sec: number;
  };
  config?: {
    timeout_seconds?: number;
    retry_count?: number;
    rate_limit_per_sec?: number;
    connection_config?: Record<string, unknown>;
  };
  connection_config?: Record<string, unknown>;
  /** How the provider's price bars are adjusted: `none` (raw) or `unknown`. */
  price_adjustment?: 'none' | 'unknown' | null;
}

export interface UsagePeriod {
  used: number;
  budget: number;
  resets_at: string;
}

/** GET /api/admin/providers/{name}/usage (metered providers only). */
export interface ProviderUsage {
  provider: string;
  day: UsagePeriod;
  month: UsagePeriod;
  /** False when the counters are process-local (Redis unavailable). */
  shared: boolean;
  day_exhausted: boolean;
}

export interface SchwabAuthStatus {
  status: 'active' | 'expired' | 'missing' | 'not_configured' | 'callback_error';
  paused: boolean;
  days_remaining?: number;
  expires_at?: string;
  error?: string;
}

export interface SchwabConnectionConfig {
  callback_url: string;
  manual_token_mode: boolean;
  force_refresh_token: boolean;
}

export interface SchwabConfigResponse {
  connection_config: SchwabConnectionConfig;
}

export interface ProviderConfig {
  enabled: boolean;
  timeout_seconds: number;
  retry_count: number;
  retry_backoff_seconds: number;
  rate_limit_per_sec: number;
  circuit_breaker_enabled: boolean;
  circuit_breaker_failure_threshold: number;
  circuit_breaker_reset_seconds: number;
  connection_config_json: string;
  connection_config?: Record<string, unknown>;
  history_store_intervals?: string[];
}

/**
 * Shape returned by GET /api/admin/credentials (routes_admin.py::list_admin_credentials).
 * Metadata only — the plaintext value is never included here. Use
 * GET /api/admin/credentials/{provider}/{credential}/reveal to obtain it.
 */
export interface CredentialMetadata {
  provider: string;
  credential_name: string;
  set: boolean;
  updated_at: string | null;
}

/** Shape returned by GET /api/admin/credentials/{provider}/{credential}/reveal. */
export interface CredentialReveal {
  provider: string;
  credential_name: string;
  value: string | null;
  set: boolean;
}

export interface ConnectionTestResult {
  status_code: number;
  success: boolean;
  message: string;
  details: Record<string, unknown>;
}

export interface SystemDefaults {
  default_price_provider?: string;
  default_company_provider?: string;
  default_options_provider?: string;
  default_news_provider?: string;
  default_volatility_provider?: string;
  default_earnings_provider?: string;
}

export interface CachePolicy {
  option_chain_seconds: number;
  historical_closed_seconds: number;
  historical_open_bar_seconds: number;
  historical_intraday_seconds: number;
  company_profile_seconds: number;
  company_search_seconds: number;
  company_news_seconds: number;
  market_status_seconds: number;
  volatility_seconds: number;
  earnings_seconds: number;
  extend_when_market_closed: boolean;
}

export interface CacheStatus {
  state: 'disabled' | 'connected' | 'unavailable';
  redis_url: string;
  policy: CachePolicy;
  defaults: CachePolicy;
  market: { state: 'session' | 'settle_grace' | 'settled'; next_open: string };
  memory: { used_memory: number; maxmemory: number } | null;
  key_counts: Record<Exclude<CacheScope, 'all'>, number> | null;
}

export type CacheScope = 'all' | 'options_chain' | 'historical_prices' | 'company_profile' | 'company_search' | 'company_news' | 'market_status' | 'volatility' | 'earnings';

export interface CacheClearResult {
  deleted: number;
  scope: CacheScope;
  provider: string | null;
}

export type StoredInterval = '1h' | '4h' | '1d' | '1w';

export interface HistoryStoreDatasetStatus {
  series: number;
  rows: number;
  oldest: string | null;
  newest: string | null;
  newest_synced_at: string | null;
  intervals?: Record<string, HistoryStoreDatasetStatus>;
}

export interface HistoryStoreStatus {
  state: 'disabled' | 'connected' | 'unavailable';
  database_url: string;
  settings: { resync_seconds: number; overlap_bars: number; migrate_on_startup: boolean };
  prices: HistoryStoreDatasetStatus | null;
  iv: HistoryStoreDatasetStatus | null;
}

export interface HistoryStoreClearResult {
  deleted_series: number;
  deleted_rows: number;
}
