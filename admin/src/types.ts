export interface Provider {
  name: string;
  enabled: boolean;
  status: 'healthy' | 'paused' | 'degraded' | 'offline' | 'disabled' | 'unavailable';
  error?: string | null;
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

export interface CredentialMetadata {
  provider_name: string;
  credential_name: string;
  set: boolean;
  updated_at?: string;
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
  logo_url?: string;
}

export interface ProviderCapabilities {
  prices: string[];
  options: string[];
  companies: string[];
  news: string[];
}
