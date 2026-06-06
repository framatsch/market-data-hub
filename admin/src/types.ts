export interface Provider {
  name: string;
  enabled: boolean;
  status: 'healthy' | 'paused' | 'degraded' | 'offline' | 'disabled';
  error?: string;
  config_summary: {
    timeout_seconds: number;
    retry_count: number;
    rate_limit_per_sec: number;
  };
}

export interface SchwabStatus {
  status: 'active' | 'expired' | 'missing';
  paused: boolean;
  days_remaining?: number;
  expires_at?: string;
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
}

export interface CredentialMetadata {
  provider_name: string;
  credential_name: string;
  set: boolean;
  updated_at?: string;
}
export interface SystemDefaults {
  default_price_provider?: string;
  default_company_provider?: string;
  default_options_provider?: string;
  default_news_provider?: string;
}

export interface ProviderCapabilities {
  prices: string[];
  options: string[];
  companies: string[];
  news: string[];
}
