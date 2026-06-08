import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Box,
  Button,
  CircularProgress,
  Typography,
  Chip,
  Alert,
  Snackbar,
} from '@mui/material';
import { fetcher } from '../../lib/api';
import type { SchwabAuthStatus } from '../../types';

export function SchwabOAuthSection() {
  
  const [isPolling, setIsPolling] = useState(false);
  const [pollTimeout, setPollTimeout] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' });

  const statusQuery = useQuery<SchwabAuthStatus>({
    queryKey: ['schwab', 'status'],
    queryFn: () => fetcher('/api/admin/schwab/auth/status'),
    refetchInterval: isPolling ? 2000 : false,
  });

  useEffect(() => {
    if (!isPolling) return;

    if (statusQuery.data?.status === 'active') {
      setIsPolling(false);
      setSnackbar({ open: true, message: 'Schwab successfully re-authorized', severity: 'success' });
    } else if (statusQuery.data?.status === 'callback_error') {
      setIsPolling(false);
      setSnackbar({ open: true, message: `Authorization failed: ${statusQuery.data.error}`, severity: 'error' });
    }
  }, [isPolling, statusQuery.data]);

  const handleReauthorize = async () => {
    try {
      setPollTimeout(false);
      const res = (await fetcher('/api/admin/schwab/auth/url')) as any;
      if (res && typeof res === 'object' && 'auth_url' in res && typeof res.auth_url === 'string') {
        window.open(res.auth_url, '_blank');
        setIsPolling(true);
        
        // Stop polling after 60 seconds
        setTimeout(() => {
          setIsPolling((current) => {
            if (current) {
              setPollTimeout(true);
              return false;
            }
            return current;
          });
        }, 60000);
      }
    } catch (err: any) {
      setSnackbar({ open: true, message: `Failed to get auth URL: ${err.message}`, severity: 'error' });
    }
  };

  if (statusQuery.isLoading) return <CircularProgress size={24} />;

  const status = statusQuery.data?.status;
  const daysRemaining = statusQuery.data?.days_remaining;

  let chipColor: 'success' | 'warning' | 'error' | 'default' = 'default';
  let statusText = status?.toUpperCase() || 'UNKNOWN';

  if (status === 'active') {
    if (daysRemaining && daysRemaining > 3) chipColor = 'success';
    else if (daysRemaining && daysRemaining <= 3) chipColor = 'warning';
  } else if (status === 'expired' || status === 'not_configured' || status === 'callback_error') {
    chipColor = 'error';
  }

  return (
    <Box sx={{ mt: 3, pt: 3, borderTop: 1, borderColor: 'divider' }}>
      <Typography variant="subtitle2" gutterBottom>OAuth Authorization</Typography>
      
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Chip 
          label={statusText} 
          color={chipColor} 
          variant={chipColor === 'default' ? 'outlined' : 'filled'} 
        />
        
        {statusQuery.data?.expires_at && (
          <Typography variant="body2" color="text.secondary">
            Expires: {new Date(statusQuery.data.expires_at).toLocaleString()} 
            {daysRemaining !== undefined && ` (${daysRemaining} days remaining)`}
          </Typography>
        )}
      </Box>

      {status === 'callback_error' && statusQuery.data?.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {statusQuery.data.error}
        </Alert>
      )}

      {isPolling ? (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mt: 2 }}>
          <CircularProgress size={20} />
          <Typography variant="body2" color="text.secondary">
            Waiting for authorization...
          </Typography>
        </Box>
      ) : (
        <Button 
          variant="contained" 
          onClick={handleReauthorize}
        >
          {status === 'active' ? 'Re-authorize' : (pollTimeout ? 'Try Again' : 'Authorize')}
        </Button>
      )}

      {pollTimeout && !isPolling && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          Authorization timed out or was cancelled.
        </Alert>
      )}

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
      >
        <Alert onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))} severity={snackbar.severity}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
