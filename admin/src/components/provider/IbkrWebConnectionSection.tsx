import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, FormControlLabel, FormHelperText, Grid, MenuItem, Snackbar, Stack,
  Switch, TextField, Typography,
} from '@mui/material';
import { fetcher, getErrorMessage } from '../../lib/api';
import type { ConnectionTestResult, ProviderConfig } from '../../types';

interface GatewayConfig {
  base_url: string;
  verify_tls: boolean;
  ca_bundle: string;
  account_id: string;
  compete: boolean;
  market_data_type: number;
  max_streams: number;
  login_url: string;
}

interface GatewaySession {
  state: 'disabled' | 'unknown' | 'unreachable' | 'login_required' | 'competing' | 'brokerage_pending' | 'ready' | 'rate_limited';
  login_url?: string;
  connected?: boolean;
  authenticated?: boolean;
  competing?: boolean;
  username?: string | null;
  account_mode?: 'live' | 'paper' | null;
  server_version?: string | null;
  sso_expires_seconds?: number | null;
  last_tickle?: string | null;
  retry_after_seconds?: number;
  last_error?: string | null;
}

const GATEWAY = '/api/admin/providers/ibkrweb';
const CONFIG_KEY = ['providerConfig', 'ibkrweb'];
const SESSION_KEY = ['providerSession', 'ibkrweb'];
const DEFAULTS: GatewayConfig = {
  base_url: 'https://127.0.0.1:5000', verify_tls: false, ca_bundle: '', account_id: '',
  compete: false, market_data_type: 3, max_streams: 80, login_url: '',
};

const STATE_LABELS: Record<GatewaySession['state'], string> = {
  disabled: 'Disabled', unknown: 'Not checked yet', unreachable: 'Gateway unreachable',
  login_required: 'Login required', competing: 'Competing session', brokerage_pending: 'Brokerage session pending',
  ready: 'Ready', rate_limited: 'Rate limited',
};

export function IbkrWebConnectionSection() {
  const queryClient = useQueryClient();
  const config = useQuery({
    queryKey: CONFIG_KEY, queryFn: ({ signal }) => fetcher<ProviderConfig>(`${GATEWAY}/config`, { signal }),
  });
  const session = useQuery({
    queryKey: SESSION_KEY, queryFn: ({ signal }) => fetcher<GatewaySession>(`${GATEWAY}/session`, { signal }),
    refetchInterval: 10_000,
  });
  const [edits, setEdits] = useState<Partial<GatewayConfig>>({});
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [notice, setNotice] = useState(false);
  const saved = { ...DEFAULTS, ...config.data?.connection_config } as GatewayConfig;
  const form = { ...saved, ...edits };
  const state = session.data;

  const save = useMutation({
    mutationFn: (values: Partial<GatewayConfig>) => fetcher<ProviderConfig>(`${GATEWAY}/gateway`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    }),
    onSuccess: (value) => {
      queryClient.setQueryData(CONFIG_KEY, value);
      setEdits({});
      setNotice(true);
      void queryClient.invalidateQueries({ queryKey: ['providers'] });
      void queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
  const sessionAction = useMutation({
    mutationFn: (action: 'init' | 'logout') => fetcher<GatewaySession>(`${GATEWAY}/session/${action}`, { method: 'POST' }),
    onSuccess: (value) => queryClient.setQueryData(SESSION_KEY, value),
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: SESSION_KEY }); },
  });
  const test = useMutation({
    mutationFn: () => fetcher<ConnectionTestResult>('/api/admin/test-connection/ibkrweb', { method: 'POST' }),
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: SESSION_KEY }); },
  });

  function change<K extends keyof GatewayConfig>(name: K, value: GatewayConfig[K]) {
    save.reset();
    setEdits((old) => ({ ...old, [name]: value }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    test.reset();
    save.mutate(edits);
  }

  if (config.isPending) return <CircularProgress size={24} />;
  if (config.error) return <Alert severity="error">{getErrorMessage(config.error)}</Alert>;

  const saveError = save.error ? getErrorMessage(save.error) : '';
  const tlsError = saveError.includes('verify_tls');
  const busy = save.isPending || sessionAction.isPending || test.isPending;
  const disabled = !state || state.state === 'disabled' || config.data?.enabled === false;
  const browserUrl = state?.login_url || saved.login_url || saved.base_url;
  const loginUrl = browserUrl.startsWith('https://') ? browserUrl : undefined;

  return (
    <Stack spacing={2}>
      <Box component="form" onSubmit={submit}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12 }}>
            <TextField fullWidth required size="small" label="Gateway URL" type="url"
              value={form.base_url} disabled={busy} onChange={(e) => change('base_url', e.target.value)} />
          </Grid>
          <Grid size={{ xs: 12 }}>
            <TextField fullWidth size="small" label="Browser login URL (optional)" type="url"
              value={form.login_url} disabled={busy} onChange={(e) => change('login_url', e.target.value)}
              helperText="Only needed when the gateway URL is not reachable from your browser, e.g. https://localhost:5000 under Compose" />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <FormControlLabel label="Verify TLS" control={<Switch checked={form.verify_tls}
              disabled={busy} onChange={(e) => change('verify_tls', e.target.checked)} />} />
            {tlsError && <FormHelperText error role="alert">{saveError}</FormHelperText>}
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth size="small" label="CA bundle (optional)" value={form.ca_bundle}
              disabled={busy} onChange={(e) => change('ca_bundle', e.target.value)} helperText="Certificate path on the server" />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth size="small" label="Account ID (optional)" value={form.account_id}
              disabled={busy} onChange={(e) => change('account_id', e.target.value)} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth select size="small" label="Market Data Type" value={form.market_data_type}
              disabled={busy} onChange={(e) => change('market_data_type', Number(e.target.value))}>
              <MenuItem value={1}>1 — Live</MenuItem><MenuItem value={2}>2 — Frozen</MenuItem>
              <MenuItem value={3}>3 — Delayed</MenuItem><MenuItem value={4}>4 — Delayed Frozen</MenuItem>
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth required size="small" label="Max streams" type="number" value={form.max_streams || ''}
              disabled={busy} slotProps={{ htmlInput: { min: 1, max: 100, step: 1 } }}
              onChange={(e) => change('max_streams', Number(e.target.value))} />
          </Grid>
          <Grid size={{ xs: 12 }}>
            <FormControlLabel label="Allow competing session" control={<Switch checked={form.compete}
              disabled={busy} onChange={(e) => change('compete', e.target.checked)} />} />
            <FormHelperText>Disconnects other IBKR sessions of this username (TWS, IB Gateway, IBKR Mobile).</FormHelperText>
          </Grid>
          <Grid size={{ xs: 12 }}><Button type="submit" variant="contained" disabled={busy}>Save</Button></Grid>
        </Grid>
      </Box>
      {saveError && !tlsError && <Alert severity="error">{saveError}</Alert>}

      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
            <Typography variant="subtitle1">Gateway session</Typography>
            {state && <Chip size="small" label={STATE_LABELS[state.state]} color={state.state === 'ready' ? 'success' : 'default'} />}
          </Stack>
          {session.error && <Alert severity="error">{getErrorMessage(session.error)}</Alert>}
          {state?.state === 'login_required' && <Alert severity="warning">Login required at the Client Portal Gateway</Alert>}
          {state?.state === 'rate_limited' && <Alert severity="warning">Gateway rate limit. Retry in {state.retry_after_seconds ?? 0} seconds.</Alert>}
          {state && state.state !== 'disabled' && (
            <Box component="dl" sx={{ m: 0, display: 'grid', gap: 0.75, gridTemplateColumns: 'auto 1fr', '& dd': { m: 0, overflowWrap: 'anywhere' } }}>
              <dt>Connected</dt><dd>{state.connected ? 'Yes' : 'No'}</dd>
              <dt>Authenticated</dt><dd>{state.authenticated ? 'Yes' : 'No'}</dd>
              <dt>Competing</dt><dd>{state.competing ? 'Yes' : 'No'}</dd>
              <dt>Account mode</dt><dd>{state.account_mode ?? '—'}</dd>
              <dt>Username</dt><dd>{state.username ?? '—'}</dd>
              <dt>Server version</dt><dd>{state.server_version ?? '—'}</dd>
              <dt>Time to expiry</dt><dd>{state.sso_expires_seconds == null ? '—' : `${state.sso_expires_seconds}s`}</dd>
              <dt>Last tickle</dt><dd>{state.last_tickle ? new Date(state.last_tickle).toLocaleString() : '—'}</dd>
              <dt>Last error</dt><dd>{state.last_error ?? '—'}</dd>
            </Box>
          )}
          <Typography variant="body2" color="text.secondary">Use a browser that reaches the gateway directly, on the same host or through an SSH tunnel.</Typography>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
            <Button component="a" href={loginUrl} target="_blank" rel="noopener noreferrer"
              variant={state?.state === 'login_required' ? 'contained' : 'outlined'} disabled={disabled || !loginUrl}>Open gateway login</Button>
            <Button variant="outlined" disabled={disabled || busy || state?.state === 'rate_limited'}
              onClick={() => sessionAction.mutate('init')}>Initialise brokerage session</Button>
            <Button variant="outlined" disabled={disabled || busy} onClick={() => test.mutate()}>Test connection</Button>
            <Button color="error" disabled={disabled || busy} onClick={() => setLogoutOpen(true)}>Logout</Button>
          </Stack>
          {sessionAction.error && <Alert severity="error">{getErrorMessage(sessionAction.error)}</Alert>}
          {test.error && <Alert severity="error">{getErrorMessage(test.error)}</Alert>}
          {test.data && <Alert severity={test.data.success ? 'success' : 'error'}>{test.data.message}</Alert>}
        </Stack>
      </Box>

      <Dialog open={logoutOpen} onClose={() => setLogoutOpen(false)} aria-labelledby="ibkrweb-logout-title">
        <DialogTitle id="ibkrweb-logout-title">Log out of the IBKR gateway?</DialogTitle>
        <DialogContent>This ends the shared session for all services using this gateway. A browser login is needed to reconnect.</DialogContent>
        <DialogActions>
          <Button onClick={() => setLogoutOpen(false)}>Cancel</Button>
          <Button color="error" onClick={() => { setLogoutOpen(false); sessionAction.mutate('logout'); }}>Log out</Button>
        </DialogActions>
      </Dialog>
      <Snackbar open={notice} autoHideDuration={6000} onClose={() => setNotice(false)}>
        <Alert severity="success" onClose={() => setNotice(false)}>IBKR Web API gateway connection updated</Alert>
      </Snackbar>
    </Stack>
  );
}
