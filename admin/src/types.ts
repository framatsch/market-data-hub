export interface Provider {
  name: string;
  enabled: boolean;
  status: 'healthy' | 'paused' | 'degraded' | 'offline' | 'disabled' | 'unavailable';
  error?: string | null;
  capabilities?: string[];
  config_summary?: {
    timeout_seconds: number;
    retry_count: number;
    rate_limit_per_sec: number;
  };
  config?: {
    timeout_seconds?: number;
    retry_count?: number;
    rate_limit_per_sec?: number;
  };
  connection_config?: Record<string, any>;
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
  connection_config?: Record<string, any>;
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
}
