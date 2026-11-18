import type { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CacheCard from '../components/CacheCard';
import { ProviderConfigSection } from '../components/provider/ProviderConfigSection';
import { ProviderSupport } from '../components/provider/ProviderSupport';
import { isMetered, parseBudget } from '../lib/budget';
import ProvidersPage from '../pages/ProvidersPage';
import SettingsPage from '../pages/SettingsPage';
import type { Provider } from '../types';

type Call = { url: string; method: string; body?: Record<string, unknown> };

const state = vi.hoisted(() => ({
  routes: {} as Record<string, unknown>,
  calls: [] as { url: string; method: string; body?: Record<string, unknown> }[],
}));

vi.mock('../lib/api', () => ({
  getErrorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  fetcher: (url: string, options: RequestInit = {}) => {
    const method = options.method ?? 'GET';
    state.calls.push({ url, method, body: options.body ? JSON.parse(String(options.body)) : undefined });
    const value = state.routes[`${method} ${url}`] ?? state.routes[url];
    return value === undefined ? Promise.reject(new Error(`unmocked ${method} ${url}`)) : Promise.resolve(value);
  },
}));

function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const lastCall = (method: string, url: string): Call | undefined =>
  [...state.calls].reverse().find((call) => call.method === method && call.url === url);

function provider(overrides: Partial<Provider> & { name: string }): Provider {
  return { enabled: true, status: 'healthy', capabilities: [], ...overrides };
}

const providerConfig = (connection: Record<string, unknown>) => ({
  enabled: true, timeout_seconds: 10, retry_count: 3, retry_backoff_seconds: 0.5,
  rate_limit_per_sec: 1, circuit_breaker_enabled: false, circuit_breaker_failure_threshold: 5,
  circuit_breaker_reset_seconds: 60, connection_config: connection, history_store_intervals: ['1d'],
});

const usage = (overrides: Record<string, unknown> = {}) => ({
  provider: 'alphavantage', shared: true, day_exhausted: false,
  day: { used: 12, budget: 25, resets_at: '2026-11-18T05:00:00+00:00' },
  month: { used: 40, budget: 0, resets_at: '2026-12-01T00:00:00+00:00' },
  ...overrides,
});

beforeEach(() => {
  state.routes = {};
  state.calls = [];
});

describe('budget helpers', () => {
  it('parses only whole non-negative numbers', () => {
    expect(['0', '25', ' 7 '].map(parseBudget)).toEqual([0, 25, 7]);
    expect(['', '-1', '1.5', 'abc', '1e3'].map(parseBudget)).toEqual([null, null, null, null, null]);
  });

  it('recognises metered providers by their budget keys', () => {
    expect(isMetered({ request_budget_per_day: 25 })).toBe(true);
    expect(isMetered({ host: 'localhost' })).toBe(false);
    expect(isMetered(undefined)).toBe(false);
  });
});

describe('Earnings capability chip', () => {
  it('is shown for providers with the earnings capability', async () => {
    state.routes['/api/admin/providers'] = [
      provider({ name: 'alphavantage', capabilities: ['prices', 'earnings'] }),
      provider({ name: 'ibkr', capabilities: ['prices', 'options'] }),
    ];
    state.routes['/api/admin/credentials'] = [];
    renderWithProviders(<ProvidersPage />);
    const row = (await screen.findByText('ALPHAVANTAGE')).closest('tr')!;
    expect(within(row).getByText('Prices · Earnings')).toBeTruthy();
    expect(within(row).getAllByText('Earnings').length).toBeGreaterThan(0);
    const other = screen.getByText('IBKR').closest('tr')!;
    expect(within(other).queryByText('Earnings')).toBeNull();
  });
});

describe('Default Earnings Provider dropdown', () => {
  it('lists earnings providers and saves the selection', async () => {
    state.routes['/api/admin/settings/defaults'] = { default_earnings_provider: '' };
    state.routes['/api/admin/settings/capabilities'] = {
      prices: ['alphavantage'], options: [], companies: [], news: [], volatility: [],
      earnings: ['alphavantage', 'financialdatasets'],
    };
    state.routes['PUT /api/admin/settings/defaults'] = {};
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />);
    await user.click(await screen.findByRole('combobox', { name: 'Default Earnings Provider' }));
    const options = within(await screen.findByRole('listbox')).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['None', 'alphavantage', 'financialdatasets']);
    await user.click(screen.getByRole('option', { name: 'alphavantage' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(lastCall('PUT', '/api/admin/settings/defaults')).toBeTruthy());
    expect(lastCall('PUT', '/api/admin/settings/defaults')?.body?.default_earnings_provider).toBe('alphavantage');
  });
});

describe('Earnings cache policy', () => {
  const policy = {
    option_chain_seconds: 900, historical_closed_seconds: 604800, historical_open_bar_seconds: 300,
    historical_intraday_seconds: 300, company_profile_seconds: 86400, company_search_seconds: 3600,
    company_news_seconds: 600, market_status_seconds: 60, volatility_seconds: 900,
    earnings_seconds: 21600, extend_when_market_closed: true,
  };

  it('edits the earnings TTL, shows its key count and offers the clear scope', async () => {
    state.routes['/api/admin/cache'] = {
      state: 'connected', redis_url: 'redis://redis:6379/0', policy, defaults: policy,
      market: { state: 'settled', next_open: '2026-11-18T14:30:00Z' }, memory: null,
      key_counts: { earnings: 3 },
    };
    state.routes['/api/admin/providers'] = [];
    state.routes['PUT /api/admin/cache/policy'] = {};
    const user = userEvent.setup();
    renderWithProviders(<CacheCard />);
    const field = await screen.findByLabelText('Earnings');
    expect((field as HTMLInputElement).value).toBe('21600');
    expect(screen.getByText('= 6 h')).toBeTruthy();
    expect(screen.getByText(/Earnings 3/)).toBeTruthy();
    await user.clear(field);
    await user.type(field, '0');
    expect(screen.getByText('= not cached')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Save cache policy' }));
    await waitFor(() => expect(lastCall('PUT', '/api/admin/cache/policy')).toBeTruthy());
    expect(lastCall('PUT', '/api/admin/cache/policy')?.body?.earnings_seconds).toBe(0);

    await user.click(screen.getByRole('button', { name: 'Clear cache…' }));
    await user.click(await screen.findByRole('combobox', { name: 'Scope' }));
    expect(screen.getByRole('option', { name: 'Earnings' })).toBeTruthy();
  });
});

describe('Provider budget settings and usage', () => {
  function routesFor(connection: Record<string, unknown>, usageOverrides = {}) {
    state.routes['/api/admin/providers/alphavantage/config'] = providerConfig(connection);
    state.routes['/api/admin/providers/alphavantage/usage'] = usage(usageOverrides);
    state.routes['/api/admin/history-store'] = { state: 'disabled' };
    state.routes['/api/admin/providers'] = [];
    state.routes['PUT /api/admin/providers/alphavantage/config'] = {};
  }
  const connection = { request_budget_per_day: 25, request_budget_per_month: 0 };
  const renderSection = () =>
    renderWithProviders(<ProviderConfigSection providerName="alphavantage" onSuccess={vi.fn()} onError={vi.fn()} />);

  it('shows the budgets, the usage with reset time and the sharing state', async () => {
    routesFor(connection);
    renderSection();
    const day = (await screen.findByLabelText('Requests per day (0 = no limit)')) as HTMLInputElement;
    expect(day.value).toBe('25');
    expect((screen.getByLabelText('Requests per month (0 = no limit)') as HTMLInputElement).value).toBe('0');
    const panel = await screen.findByTestId('provider-usage');
    expect(within(panel).getByText('12 / 25')).toBeTruthy();
    expect(within(panel).getByText('40 / no limit')).toBeTruthy();
    expect(within(panel).getAllByText(/resets/)).toHaveLength(2);
    expect(within(panel).getByText('shared')).toBeTruthy();
    expect(screen.queryByText('Connection Config (JSON)')).toBeNull();
  });

  it('flags process-local counters and an exhausted day', async () => {
    routesFor(connection, { shared: false, day_exhausted: true });
    renderSection();
    const panel = await screen.findByTestId('provider-usage');
    expect(within(panel).getByText('this replica only')).toBeTruthy();
    expect(within(panel).getByText(/daily quota as exhausted/)).toBeTruthy();
  });

  it('rejects invalid budgets and saves valid ones into the connection config', async () => {
    routesFor({ ...connection, other: 'kept' });
    const user = userEvent.setup();
    renderSection();
    const day = await screen.findByLabelText('Requests per day (0 = no limit)');
    const save = screen.getByRole('button', { name: 'Save Configuration' });
    await user.clear(day);
    await user.type(day, '-1');
    expect(screen.getByText('Enter a whole number, 0 or greater.')).toBeTruthy();
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await user.clear(day);
    await user.type(day, '10');
    expect((save as HTMLButtonElement).disabled).toBe(false);
    await user.click(save);
    await waitFor(() => expect(lastCall('PUT', '/api/admin/providers/alphavantage/config')).toBeTruthy());
    expect(lastCall('PUT', '/api/admin/providers/alphavantage/config')?.body?.connection_config).toEqual({
      request_budget_per_day: 10, request_budget_per_month: 0, other: 'kept',
    });
  });

  it('keeps the JSON editor and shows no budget for unmetered providers', async () => {
    state.routes['/api/admin/providers/ibkr/config'] = providerConfig({ host: 'localhost' });
    state.routes['/api/admin/history-store'] = { state: 'disabled' };
    state.routes['/api/admin/providers'] = [];
    renderWithProviders(<ProviderConfigSection providerName="ibkr" onSuccess={vi.fn()} onError={vi.fn()} />);
    expect(await screen.findByText('Connection Config (JSON)')).toBeTruthy();
    expect(screen.queryByTestId('provider-budget')).toBeNull();
    expect(state.calls.some((call) => call.url.endsWith('/usage'))).toBe(false);
  });
});

describe('stored history interval labels', () => {
  const renderLabels = async (name: string, price_support: Provider['price_support']) => {
    state.routes[`/api/admin/providers/${name}/config`] = providerConfig({});
    state.routes['/api/admin/history-store'] = { state: 'enabled' };
    state.routes['/api/admin/providers'] = [provider({ name, price_support })];
    renderWithProviders(<ProviderConfigSection providerName={name} onSuccess={vi.fn()} onError={vi.fn()} />);
    return within(await screen.findByTestId('stored-intervals'));
  };

  it('marks intervals without a smaller native source as not available but keeps them selectable', async () => {
    const labels = await renderLabels('financialdatasets', {
      price_sec_types: ['stock'], price_history_sec_types: ['stock'],
      native_intervals: ['1d', '1w'], derived_intervals: [],
    });
    expect(labels.getByLabelText('1h (not available)')).toBeTruthy();
    expect((labels.getByLabelText('4h (not available)') as HTMLInputElement).disabled).toBe(false);
    expect(labels.getByLabelText('1d (native)')).toBeTruthy();
    expect(labels.getByLabelText('1w (native)')).toBeTruthy();
  });

  it('marks aggregatable intervals as derived', async () => {
    const labels = await renderLabels('schwab', {
      price_sec_types: ['stock'], price_history_sec_types: ['stock'],
      native_intervals: ['30m', '1d', '1w'], derived_intervals: ['1h', '4h'],
    });
    expect(labels.getByLabelText('1h (derived)')).toBeTruthy();
    expect(labels.getByLabelText('4h (derived)')).toBeTruthy();
  });
});

describe('price adjustment in the provider details', () => {
  const support = { price_sec_types: ['stock'], price_history_sec_types: ['stock'], native_intervals: ['1d', '1w'] };

  it.each([['none', 'none'], ['unknown', 'unknown']] as const)('shows %s', (value, text) => {
    renderWithProviders(
      <ProviderSupport provider={provider({ name: 'p', price_support: support, price_adjustment: value })} />,
    );
    const label = screen.getByText('Price adjustment');
    expect(within(label.parentElement!).getByText(text)).toBeTruthy();
  });

  it('is absent for providers that do not state it', () => {
    renderWithProviders(<ProviderSupport provider={provider({ name: 'p', price_support: support })} />);
    expect(screen.queryByText('Price adjustment')).toBeNull();
  });
});
