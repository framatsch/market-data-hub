import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Button,
  CircularProgress,
  Typography,
  Chip,
  Alert,
  Snackbar,
  Switch,
  FormControlLabel,
  TextField,
  Divider,
  Tooltip,
} from '@mui/material';
import { fetcher, getErrorMessage } from '../../lib/api';
import type { SchwabAuthStatus, SchwabConfigResponse } from '../../types';

export function SchwabOAuthSection() {
  const qc = useQueryClient();

  const [isPolling, setIsPolling] = useState(false);
  const [pollTimeout, setPollTimeout] = useState(false);
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'success' as 'success' | 'error' | 'info',
  });

  // --- Remote state ---
  const statusQuery = useQuery<SchwabAuthStatus>({
    queryKey: ['schwab', 'status'],
    queryFn: () => fetcher('/api/admin/schwab/auth/status'),
  });

  const configQuery = useQuery<SchwabConfigResponse>({
    queryKey: ['schwab', 'config'],
    queryFn: () => fetcher('/api/admin/schwab/config'),
  });

  // --- Local editable config state ---
  const [callbackUrlEdit, setCallbackUrl] = useState<string | undefined>();
  const [manualTokenModeEdit, setManualTokenMode] = useState<boolean | undefined>();
  const [forceRefreshTokenEdit, setForceRefreshToken] = useState<boolean | undefined>();
  const callbackUrl = callbackUrlEdit ?? configQuery.data?.connection_config.callback_url ?? '';
  const manualTokenMode = manualTokenModeEdit ?? configQuery.data?.connection_config.manual_token_mode ?? false;
  const forceRefreshToken = forceRefreshTokenEdit ?? configQuery.data?.connection_config.force_refresh_token ?? true;
  const [manualTokenJson, setManualTokenJson] = useState('');

  // Poll the external OAuth flow, with cleanup on completion, retry and unmount.
  const { refetch: refetchStatus } = statusQuery;
  useEffect(() => {
    if (!isPolling) return;
    let cancelled = false;
    const checkStatus = async () => {
      const result = await refetchStatus();
      if (cancelled) return;
      if (result.data?.status === 'active') {
        setIsPolling(false);
        setSnackbar({ open: true, message: 'Schwab successfully authorized', severity: 'success' });
      } else if (result.data?.status === 'callback_error') {
        setIsPolling(false);
        setSnackbar({ open: true, message: `Authorization failed: ${result.data.error}`, severity: 'error' });
      }
    };
    void checkStatus();
    const interval = window.setInterval(() => { void checkStatus(); }, 2000);
    const timeout = window.setTimeout(() => {
      setIsPolling(false);
      setPollTimeout(true);
    }, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, [isPolling, refetchStatus]);

  // --- Mutations ---
  const saveConfigMutation = useMutation({
    mutationFn: () =>
      fetcher('/api/admin/schwab/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          callback_url: callbackUrl,
          manual_token_mode: manualTokenMode,
          force_refresh_token: forceRefreshToken,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schwab', 'config'] });
      setSnackbar({ open: true, message: 'Configuration saved', severity: 'success' });
    },
    onError: (err) =>
      setSnackbar({ open: true, message: `Error: ${err.message}`, severity: 'error' }),
  });

  const saveManualTokenMutation = useMutation({
    mutationFn: () => {
      const value = manualTokenJson.trim();
      const isUrl = value.startsWith('http');
      if (isUrl) {
        return fetcher('/api/admin/schwab/auth/callback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ received_url: value }),
        });
      } else {
        return fetcher('/api/admin/schwab/auth/token/manual', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token_json: value }),
        });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schwab', 'status'] });
      setManualTokenJson('');
      setSnackbar({ open: true, message: 'Token saved — Schwab active', severity: 'success' });
    },
    onError: (err) =>
      setSnackbar({ open: true, message: `Token Error: ${err.message}`, severity: 'error' }),
  });

  // --- OAuth-Redirect flow ---
  const handleReauthorize = async () => {
    try {
      setPollTimeout(false);
      const res = await fetcher<{ auth_url: string }>('/api/admin/schwab/auth/url');
      if (res && typeof res === 'object' && 'auth_url' in res && typeof res.auth_url === 'string') {
        window.open(res.auth_url, '_blank');
        setIsPolling(true);
      }
    } catch (err: unknown) {
      setSnackbar({ open: true, message: `Auth URL Error: ${getErrorMessage(err)}`, severity: 'error' });
    }
  };

  // --- Status chip ---
  const status = statusQuery.data?.status;
  const daysRemaining = statusQuery.data?.days_remaining;
  let chipColor: 'success' | 'warning' | 'error' | 'default' = 'default';

  if (status === 'active') {
    chipColor = daysRemaining && daysRemaining > 3 ? 'success' : 'warning';
  } else if (status === 'expired' || status === 'not_configured' || status === 'callback_error') {
    chipColor = 'error';
  }

  if (statusQuery.isLoading || configQuery.isLoading) return <CircularProgress size={24} />;

  return (
    <Box sx={{ mt: 3, pt: 3, borderTop: 1, borderColor: 'divider' }}>
      <Typography variant="subtitle2" gutterBottom>
        OAuth Authorization
      </Typography>

      {/* Status */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Chip
          label={status?.toUpperCase() ?? 'UNKNOWN'}
          color={chipColor}
          variant={chipColor === 'default' ? 'outlined' : 'filled'}
        />
        {statusQuery.data?.expires_at && (
          <Typography variant="body2" color="text.secondary">
            Expires at: {new Date(statusQuery.data.expires_at).toLocaleString()}
            {daysRemaining !== undefined && ` (${daysRemaining} days)`}
          </Typography>
        )}
      </Box>

      {status === 'callback_error' && statusQuery.data?.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {statusQuery.data.error}
        </Alert>
      )}

      <Divider sx={{ my: 2 }} />

      {/* ── Konfiguration ── */}
      <Typography variant="subtitle2" gutterBottom>
        Configuration
      </Typography>

      {/* Redirect-URI */}
      <TextField
        label="Redirect URI (callback_url)"
        value={callbackUrl}
        onChange={(e) => setCallbackUrl(e.target.value)}
        fullWidth
        size="small"
        sx={{ mb: 1 }}
        helperText="OAuth2 Redirect URI — must exactly match the Schwab Developer Portal."
      />

      {/* Manual Token Mode */}
      <Tooltip title="If active: OAuth redirect is disabled. Token JSON is inserted manually.">
        <FormControlLabel
          control={
            <Switch
              checked={manualTokenMode}
              onChange={(e) => setManualTokenMode(e.target.checked)}
              size="small"
            />
          }
          label="Manual Token Mode"
        />
      </Tooltip>

      {/* Force Refresh Token */}
      <Tooltip title="Calls client.update_tokens(force_refresh_token=True) right after client initialization (Schwabdev recommendation for weekend refresh).">
        <FormControlLabel
          control={
            <Switch
              checked={forceRefreshToken}
              onChange={(e) => setForceRefreshToken(e.target.checked)}
              size="small"
            />
          }
          label="force_refresh_token on Client-Init (default: on)"
          sx={{ display: 'block' }}
        />
      </Tooltip>

      <Box sx={{ mt: 1.5 }}>
        <Button
          variant="outlined"
          size="small"
          onClick={() => saveConfigMutation.mutate()}
          disabled={saveConfigMutation.isPending}
        >
          {saveConfigMutation.isPending ? <CircularProgress size={16} /> : 'Save Configuration'}
        </Button>
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* ── OAuth-Flow oder Manueller Token ── */}
      {manualTokenMode ? (
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Insert Token manually
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Open the authorization link manually, log in, and paste the complete Callback URL or Token JSON from the browser here.
          </Typography>
          <TextField
            label="Callback URL or Token JSON"
            value={manualTokenJson}
            onChange={(e) => setManualTokenJson(e.target.value)}
            multiline
            minRows={4}
            fullWidth
            size="small"
            placeholder='https://127.0.0.1... or {"token": {...}}'
            sx={{ mb: 1 }}
          />
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Button
              variant="outlined"
              size="small"
              onClick={handleReauthorize}
            >
              Open Auth Link
            </Button>
            <Button
              variant="contained"
              size="small"
              onClick={() => saveManualTokenMutation.mutate()}
              disabled={saveManualTokenMutation.isPending || !manualTokenJson.trim()}
            >
              {saveManualTokenMutation.isPending ? <CircularProgress size={16} /> : 'Save Token'}
            </Button>
          </Box>
        </Box>
      ) : (
        <Box>
          {isPolling ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mt: 1 }}>
              <CircularProgress size={20} />
              <Typography variant="body2" color="text.secondary">
                Waiting for authorization...
              </Typography>
            </Box>
          ) : (
            <Button variant="contained" onClick={handleReauthorize}>
              {status === 'active'
                ? 'Re-authorize'
                : pollTimeout
                  ? 'Try again'
                  : 'Authorize'}
            </Button>
          )}

          {pollTimeout && !isPolling && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Authorization expired or cancelled.
            </Alert>
          )}
        </Box>
      )}

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
      >
        <Alert
          onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
          severity={snackbar.severity}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
