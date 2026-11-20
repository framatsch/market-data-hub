import type { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { IbkrWebConnectionSection } from '../components/provider/IbkrWebConnectionSection';
import { IBKR_SINGLE_SESSION_WARNING, IBKR_WEB_LABEL } from '../lib/ibkr';
import ProvidersPage from '../pages/ProvidersPage';

const fetcher = vi.hoisted(() => vi.fn());
vi.mock('../lib/api', () => ({ fetcher, getErrorMessage: (error: Error) => error.message }));

const base = '/api/admin/providers/ibkrweb';

function mount(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => { fetcher.mockReset(); });

it('shows gateway defaults and preserves input on a TLS validation error', async () => {
  fetcher.mockImplementation(async (url: string, options: RequestInit = {}) => {
    if (url === `${base}/config`) return { enabled: true };
    if (url === `${base}/session`) return { state: 'login_required' };
    if (url === `${base}/gateway` && options.method === 'PUT') {
      expect(JSON.parse(String(options.body))).toEqual({ base_url: 'https://10.0.0.5:5000' });
      throw new Error('verify_tls must be true for a non-local gateway');
    }
    throw new Error(`Unexpected request ${url}`);
  });
  const user = userEvent.setup();
  mount(<IbkrWebConnectionSection />);
  const url = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Gateway URL' });
  expect(url.value).toBe('https://127.0.0.1:5000');
  expect(screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Max streams' }).value).toBe('80');
  expect((await screen.findByRole('link', { name: 'Open gateway login' })).getAttribute('href')).toBe(url.value);
  await user.clear(url);
  await user.type(url, 'https://10.0.0.5:5000');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByText('verify_tls must be true for a non-local gateway')).toBeTruthy();
  expect(url.value).toBe('https://10.0.0.5:5000');
});

it('opens the browser login URL instead of the compose service name', async () => {
  fetcher.mockImplementation(async (url: string) => {
    if (url === `${base}/config`) {
      return { enabled: true, connection_config: { base_url: 'https://ibkr-cpgw:5000', login_url: 'https://localhost:5000' } };
    }
    if (url === `${base}/session`) return { state: 'login_required', login_url: 'https://localhost:5000' };
    throw new Error(`Unexpected request ${url}`);
  });
  mount(<IbkrWebConnectionSection />);
  expect((await screen.findByRole('link', { name: 'Open gateway login' })).getAttribute('href')).toBe('https://localhost:5000');
  expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Browser login URL (optional)' }).value).toBe('https://localhost:5000');
});

it('shows session metadata and only logs out after confirmation', async () => {
  let state = { state: 'ready', authenticated: true, username: 'testuser', account_mode: 'paper' };
  fetcher.mockImplementation(async (url: string) => {
    if (url === `${base}/config`) return { enabled: true, connection_config: { base_url: 'https://localhost:5000' } };
    if (url === `${base}/session`) return state;
    if (url === `${base}/session/logout`) {
      state = { state: 'login_required', authenticated: false, username: '', account_mode: '' };
      return state;
    }
    throw new Error(`Unexpected request ${url}`);
  });
  const user = userEvent.setup();
  mount(<IbkrWebConnectionSection />);
  expect(await screen.findByText('testuser')).toBeTruthy();
  expect(screen.getByText('paper')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Logout' }));
  expect(fetcher.mock.calls.some(([url]) => url === `${base}/session/logout`)).toBe(false);
  const modal = await screen.findByRole('dialog');
  await user.click(within(modal).getByRole('button', { name: 'Log out' }));
  expect(await screen.findByText('Login required at the Client Portal Gateway')).toBeTruthy();
});

it('routes to the dedicated connection form and hides raw connection JSON', async () => {
  fetcher.mockImplementation(async (url: string) => {
    if (url === '/api/admin/providers') return [{
      name: 'ibkrweb', enabled: true, status: 'healthy',
      warnings: ['ibkr_single_session'], capabilities: ['prices', 'options', 'companies', 'volatility'],
    }];
    if (url === '/api/admin/credentials') return [];
    if (url === `${base}/config`) return { enabled: true, connection_config: { base_url: 'https://localhost:5000' } };
    if (url === `${base}/session`) return { state: 'ready' };
    throw new Error(`Unexpected request ${url}`);
  });
  const user = userEvent.setup();
  mount(<ProvidersPage />);
  const row = (await screen.findByText(IBKR_WEB_LABEL)).closest('tr')!;
  expect(within(row).getByText('Volatility')).toBeTruthy();
  expect(within(row).queryByText('News')).toBeNull();
  expect(screen.getByText(IBKR_SINGLE_SESSION_WARNING)).toBeTruthy();
  await user.click(within(row).getByRole('button', { name: 'expand row' }));
  expect(await screen.findByRole('textbox', { name: 'Gateway URL' })).toBeTruthy();
  await user.click(screen.getByRole('tab', { name: 'Configuration' }));
  await waitFor(() => expect(screen.queryByText('Connection Config (JSON)')).toBeNull());
});
