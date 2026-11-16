import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, FormControl, FormControlLabel, InputLabel, MenuItem, Paper, Select, Snackbar,
  Stack, TextField, Typography,
} from '@mui/material';
import { fetcher } from '../lib/api';
import type { HistoryStoreClearResult, HistoryStoreDatasetStatus, HistoryStoreStatus, Provider } from '../types';

function Line({ label, data }: { label: string; data: HistoryStoreDatasetStatus | null }) {
  if (!data) return null;
  return (
    <Typography variant="body2">
      {label}: {data.series} series · {data.rows} rows
      {data.oldest && data.newest ? ` · ${data.oldest} to ${data.newest}` : ''}
      {data.newest_synced_at ? ` · last sync ${new Date(data.newest_synced_at).toLocaleString()}` : ''}
      {data.intervals && Object.keys(data.intervals).length > 0
        ? ` (${Object.entries(data.intervals).map(([interval, item]) => `${interval}: ${item.rows}`).join(', ')})`
        : ''}
    </Typography>
  );
}

export default function HistoryStoreCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [dataset, setDataset] = useState<'all' | 'prices' | 'iv'>('all');
  const [symbol, setSymbol] = useState('');
  const [provider, setProvider] = useState('');
  const [interval, setInterval] = useState('');
  const [success, setSuccess] = useState('');
  const status = useQuery<HistoryStoreStatus>({ queryKey: ['historyStore'], queryFn: () => fetcher('/api/admin/history-store'), refetchInterval: 30000 });
  const providers = useQuery<Provider[]>({ queryKey: ['providers'], queryFn: () => fetcher('/api/admin/providers') });
  const clear = useMutation<HistoryStoreClearResult, Error>({
    mutationFn: () => fetcher('/api/admin/history-store/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirm: true, dataset, symbol: symbol.trim() || null, provider: provider || null,
        interval: dataset === 'iv' ? null : interval || null,
      }),
    }),
    onSuccess: result => {
      setOpen(false);
      setSuccess(`Deleted ${result.deleted_series} series and ${result.deleted_rows} rows.`);
      void queryClient.invalidateQueries({ queryKey: ['historyStore'] });
    },
  });
  const data = status.data;
  const connected = data?.state === 'connected';
  return (
    <Paper sx={{ p: 3, maxWidth: 900, mt: 3 }}>
      <Stack direction="row" sx={{ alignItems: 'center' }} spacing={2}>
        <Typography variant="h5">History Store</Typography>
        {data && <Chip label={data.state} color={connected ? 'success' : 'default'} />}
      </Stack>
      {status.isLoading && <CircularProgress sx={{ mt: 2 }} />}
      {status.error && <Alert severity="error" sx={{ mt: 2 }}>{status.error.message}</Alert>}
      {data?.state === 'disabled' && <Alert severity="info" sx={{ mt: 2 }}>The history store is not configured: DATABASE_URL is not set. History is loaded from the providers for every request.</Alert>}
      {data?.state === 'unavailable' && <Alert severity="warning" sx={{ mt: 2 }}>The database cannot be reached. Requests are served from the providers until it is back.</Alert>}
      {data && data.state !== 'disabled' && <Typography sx={{ mt: 2 }} variant="body2">Database: {data.database_url}</Typography>}
      {connected && data && <>
        <Line label="Prices" data={data.prices} />
        <Line label="IV" data={data.iv} />
        <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
          Resync every {data.settings.resync_seconds} s · overlap {data.settings.overlap_bars} bars. Stored intervals are chosen per provider in its details.
        </Typography>
      </>}
      {data && data.state !== 'disabled' && (
        <Button sx={{ mt: 2 }} color="error" variant="outlined" disabled={!connected}
          onClick={() => { clear.reset(); setAcknowledged(false); setDataset('all'); setSymbol(''); setProvider(''); setInterval(''); setOpen(true); }}>Clear…</Button>
      )}
      <Dialog open={open} onClose={() => { if (!clear.isPending) setOpen(false); }} fullWidth maxWidth="sm">
        <DialogTitle>Clear stored history?</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>The next requests reload the deleted series from the providers.</Alert>
          <Stack spacing={2}>
            <FormControl fullWidth>
              <InputLabel id="hs-dataset-label">Dataset</InputLabel>
              <Select labelId="hs-dataset-label" label="Dataset" value={dataset} disabled={clear.isPending} onChange={e => setDataset(e.target.value as 'all' | 'prices' | 'iv')}>
                <MenuItem value="all">All</MenuItem>
                <MenuItem value="prices">Prices</MenuItem>
                <MenuItem value="iv">Implied volatility</MenuItem>
              </Select>
            </FormControl>
            <TextField label="Symbol (optional)" value={symbol} disabled={clear.isPending} onChange={e => setSymbol(e.target.value)} />
            <FormControl fullWidth>
              <InputLabel id="hs-provider-label">Provider</InputLabel>
              <Select labelId="hs-provider-label" label="Provider" value={provider} disabled={clear.isPending} onChange={e => setProvider(e.target.value)}>
                <MenuItem value="">All providers</MenuItem>
                {providers.data?.map(p => <MenuItem key={p.name} value={p.name}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl fullWidth disabled={dataset === 'iv' || clear.isPending}>
              <InputLabel id="hs-interval-label">Interval</InputLabel>
              <Select labelId="hs-interval-label" label="Interval" value={interval} onChange={e => setInterval(e.target.value)}>
                <MenuItem value="">All intervals</MenuItem>
                {['1h', '4h', '1d', '1w'].map(item => <MenuItem key={item} value={item}>{item}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControlLabel control={<Checkbox checked={acknowledged} disabled={clear.isPending} onChange={e => setAcknowledged(e.target.checked)} />}
              label="I understand that the deleted history is loaded from the providers again and may trigger rate limits." />
            {clear.error && <Alert severity="error">{clear.error.message}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={clear.isPending} onClick={() => setOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" disabled={!acknowledged || clear.isPending || !connected} onClick={() => clear.mutate()}>{clear.isPending ? 'Clearing…' : 'Clear history'}</Button>
        </DialogActions>
      </Dialog>
      <Snackbar open={!!success} autoHideDuration={6000} onClose={() => setSuccess('')}>
        <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>
      </Snackbar>
    </Paper>
  );
}
