import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControl, FormControlLabel, InputLabel,
  LinearProgress, MenuItem, Paper, Select, Snackbar, Stack, Switch, TextField, Typography,
} from '@mui/material';
import { fetcher } from '../lib/api';
import type { CacheClearResult, CachePolicy, CacheScope, CacheStatus, Provider } from '../types';

const ttlFields = [
  ['option_chain_seconds', 'Option chains'],
  ['historical_closed_seconds', 'Closed historical ranges'],
  ['historical_open_bar_seconds', 'Open bar (daily and longer)'],
  ['historical_intraday_seconds', 'Intraday bars'],
  ['company_profile_seconds', 'Company profiles'],
  ['company_search_seconds', 'Company search'],
  ['company_news_seconds', 'Company news'],
  ['market_status_seconds', 'Market status'],
] as const;

const cacheScopes = [
  ['options_chain', 'Option chains'],
  ['historical_prices', 'Historical prices'],
  ['company_profile', 'Company profiles'],
  ['company_search', 'Company search'],
  ['company_news', 'Company news'],
  ['market_status', 'Market status'],
] as const;

function duration(seconds: number): string {
  if (!seconds) return 'not cached';
  if (seconds % 86400 === 0) return `${seconds / 86400} d`;
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

function PolicyForm({ initial, onSaved }: { initial: CachePolicy; onSaved: () => void }) {
  const [fields, setFields] = useState(() => Object.fromEntries(ttlFields.map(([key]) => [key, String(initial[key])])));
  const [extend, setExtend] = useState(initial.extend_when_market_closed);
  const invalid = ttlFields.some(([key]) => fields[key] === '' || !Number.isInteger(Number(fields[key])) || Number(fields[key]) < 0 || Number(fields[key]) > 2592000);
  const save = useMutation({
    mutationFn: () => fetcher('/api/admin/cache/policy', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...Object.fromEntries(ttlFields.map(([key]) => [key, Number(fields[key])])), extend_when_market_closed: extend }),
    }),
    onSuccess: onSaved,
  });
  return (
    <Box component="form" onSubmit={e => { e.preventDefault(); if (!invalid) save.mutate(); }}>
      <Typography variant="h6" sx={{ mt: 2 }}>Cache policy</Typography>
      <Typography variant="body2" color="text.secondary">Seconds, 0 = not cached. Maximum: 30 days. Intraday TTL is capped at the bar length.</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mt: 2 }}>
        {ttlFields.map(([key, label]) => (
          <TextField key={key} label={label} type="number" value={fields[key]}
            onChange={e => setFields({ ...fields, [key]: e.target.value })}
            slotProps={{ htmlInput: { min: 0, max: 2592000, step: 1 } }}
            helperText={`= ${duration(Number(fields[key]))}`} disabled={save.isPending} />
        ))}
      </Box>
      <FormControlLabel sx={{ mt: 2 }} control={<Switch checked={extend} disabled={save.isPending} onChange={e => setExtend(e.target.checked)} />}
        label="Keep entries until next market open while the market is closed" />
      <Typography variant="body2" color="text.secondary">The extension applies only to option chains and historical prices. US session model: 09:30–16:00 ET, with 30 min settle grace (extended hours: 04:00–20:00). Holidays count as weekdays. Disable the extension for non-US symbols. Market status TTL is capped at the next session transition.</Typography>
      <Alert severity="info" sx={{ my: 2 }}>Changes apply to new entries only. Existing entries keep their TTL; use Clear cache to apply a change immediately.</Alert>
      {save.error && <Alert severity="error" sx={{ mb: 2 }}>{save.error.message}</Alert>}
      <Button type="submit" variant="contained" disabled={invalid || save.isPending}>{save.isPending ? 'Saving…' : 'Save cache policy'}</Button>
    </Box>
  );
}

export default function CacheCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [scope, setScope] = useState<CacheScope>('all');
  const [provider, setProvider] = useState('');
  const [success, setSuccess] = useState('');
  const status = useQuery<CacheStatus>({ queryKey: ['cacheStatus'], queryFn: () => fetcher('/api/admin/cache'), refetchInterval: 30000 });
  const providers = useQuery<Provider[]>({ queryKey: ['providers'], queryFn: () => fetcher('/api/admin/providers') });
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['cacheStatus'] }); };
  const clear = useMutation<CacheClearResult, Error>({
    mutationFn: () => fetcher('/api/admin/cache/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true, scope, provider: provider || null }),
    }),
    onSuccess: result => { setOpen(false); setSuccess(`Cleared ${result.deleted} cache entries.`); refresh(); },
  });
  const data = status.data;
  const memory = data?.memory;
  const available = data?.state === 'connected';
  return (
    <Paper sx={{ p: 3, mt: 3, maxWidth: 900 }}>
      <Stack direction="row" sx={{ alignItems: 'center' }} spacing={2}>
        <Typography variant="h5">Response Cache</Typography>
        {data && <Chip label={data.state} color={available ? 'success' : 'default'} />}
      </Stack>
      {status.isLoading && <CircularProgress sx={{ mt: 2 }} />}
      {status.error && <Alert severity="error" sx={{ mt: 2 }}>{status.error.message}</Alert>}
      {data && <>
        <Typography sx={{ mt: 2 }} variant="body2">Redis: {data.redis_url}</Typography>
        <Typography variant="body2">Market: {data.market.state === 'session' ? 'Session' : data.market.state === 'settle_grace' ? 'Settle grace' : `Settled until ${new Date(data.market.next_open).toLocaleString()}`}</Typography>
        {memory && <Box sx={{ my: 2 }}>
          <Typography variant="body2">Memory: {(memory.used_memory / 1048576).toFixed(1)} MiB / {memory.maxmemory ? `${(memory.maxmemory / 1048576).toFixed(0)} MiB` : 'unlimited'}</Typography>
          {memory.maxmemory > 0 && <LinearProgress variant="determinate" value={Math.min(100, memory.used_memory / memory.maxmemory * 100)} />}
        </Box>}
        <Typography variant="body2">Keys (HTTP + MCP): {cacheScopes.map(([key, label]) => `${label} ${data.key_counts?.[key] ?? '—'}`).join(' · ')}</Typography>
        {!available && <Alert severity="info" sx={{ mt: 2 }}>Cache {data.state}; requests are served live. Clearing is unavailable, but policy settings can still be saved.</Alert>}
        <PolicyForm key={JSON.stringify(data.policy)} initial={data.policy} onSaved={() => { setSuccess('Cache policy saved.'); refresh(); }} />
      </>}
      <Box sx={{ mt: 3 }}>
        <Button color="error" variant="outlined" disabled={!available} onClick={() => { clear.reset(); setAcknowledged(false); setScope('all'); setProvider(''); setOpen(true); }}>Clear cache…</Button>
      </Box>
      <Dialog open={open} onClose={() => { if (!clear.isPending) setOpen(false); }} fullWidth maxWidth="sm">
        <DialogTitle>Clear response cache?</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>Following requests will hit broker APIs live. Clearing many entries can cause a burst of requests and rate-limit errors.</Alert>
          <Stack spacing={2}>
            <FormControl fullWidth>
              <InputLabel id="cache-scope-label">Scope</InputLabel>
              <Select labelId="cache-scope-label" label="Scope" value={scope} disabled={clear.isPending} onChange={e => setScope(e.target.value as CacheScope)}>
                <MenuItem value="all">All MDH cache entries</MenuItem>
                {cacheScopes.map(([key, label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl fullWidth>
              <InputLabel id="cache-provider-label">Provider</InputLabel>
              <Select labelId="cache-provider-label" label="Provider" value={provider} disabled={clear.isPending} onChange={e => setProvider(e.target.value)}>
                <MenuItem value="">All providers</MenuItem>
                {providers.data?.map(p => <MenuItem key={p.name} value={p.name}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControlLabel control={<Checkbox checked={acknowledged} disabled={clear.isPending} onChange={e => setAcknowledged(e.target.checked)} />}
              label="I understand that subsequent requests hit broker APIs live and may trigger rate limits." />
            {clear.error && <Alert severity="error">{clear.error.message}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={clear.isPending} onClick={() => setOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" disabled={!acknowledged || clear.isPending || !available} onClick={() => clear.mutate()}>{clear.isPending ? 'Clearing…' : 'Clear cache'}</Button>
        </DialogActions>
      </Dialog>
      <Snackbar open={!!success} autoHideDuration={6000} onClose={() => setSuccess('')}>
        <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>
      </Snackbar>
    </Paper>
  );
}
