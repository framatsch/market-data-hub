import React, { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  TextField,
  Button,
  Grid,
  CircularProgress,
  MenuItem,
  Alert,
  Snackbar,
} from '@mui/material';
import { fetcher } from '../../lib/api';
import type { ProviderConfig } from '../../types';

interface IbkrConnectionConfig {
  host: string;
  port: number;
  client_id?: number;
  account_id?: string;
  env?: 'live' | 'paper';
  market_data_type?: number;
}

export function IbkrConnectionSection() {
  const queryClient = useQueryClient();
  
  const configQuery = useQuery<ProviderConfig>({
    queryKey: ['providerConfig', 'ibkr'],
    queryFn: () => fetcher('/api/admin/providers/ibkr/config'),
  });

  const [formData, setFormData] = useState<Partial<IbkrConnectionConfig>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; details?: any } | null>(null);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' });

  useEffect(() => {
    if (configQuery.data?.connection_config && Object.keys(formData).length === 0) {
      setFormData(configQuery.data.connection_config as Partial<IbkrConnectionConfig>);
    }
  }, [configQuery.data, formData]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'number' ? (value ? parseFloat(value) : undefined) : value,
    }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setTestResult(null);

    try {
      await fetcher('/api/admin/providers/ibkr/gateway', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      setSnackbar({ open: true, message: 'IBKR gateway connection updated', severity: 'success' });
      queryClient.invalidateQueries({ queryKey: ['providerConfig', 'ibkr'] });
      queryClient.invalidateQueries({ queryKey: ['providers'] });
    } catch (err: any) {
      setSnackbar({ open: true, message: `Update failed: ${err.message}`, severity: 'error' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await fetcher('/api/admin/test-connection/ibkr', {
        method: 'POST',
      });
      setTestResult(res as { success: boolean; message: string; details?: any });
    } catch (err: any) {
      setTestResult({ success: false, message: err.message });
    } finally {
      setIsTesting(false);
    }
  };

  if (configQuery.isLoading) return <CircularProgress size={24} />;

  return (
    <Box>
      <Box component="form" onSubmit={handleSave}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              label="Host"
              name="host"
              value={formData.host || ''}
              onChange={handleChange}
              size="small"
              required
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              label="Port"
              name="port"
              type="number"
              value={formData.port ?? ''}
              onChange={handleChange}
              size="small"
              required
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              label="Client ID"
              name="client_id"
              type="number"
              value={formData.client_id ?? ''}
              onChange={handleChange}
              size="small"
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              label="Account ID"
              name="account_id"
              value={formData.account_id || ''}
              onChange={handleChange}
              size="small"
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              select
              label="Environment"
              name="env"
              value={formData.env || ''}
              onChange={handleChange}
              size="small"
            >
              <MenuItem value="live">Live</MenuItem>
              <MenuItem value="paper">Paper</MenuItem>
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              fullWidth
              select
              label="Market Data Type"
              name="market_data_type"
              value={formData.market_data_type || ''}
              onChange={handleChange}
              size="small"
            >
              <MenuItem value={1}>1 - Live</MenuItem>
              <MenuItem value={2}>2 - Frozen</MenuItem>
              <MenuItem value={3}>3 - Delayed</MenuItem>
              <MenuItem value={4}>4 - Delayed Frozen</MenuItem>
            </TextField>
          </Grid>

          <Grid size={{ xs: 12 }} sx={{ display: 'flex', gap: 2, mt: 1 }}>
            <Button
              type="submit"
              variant="contained"
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </Button>
            <Button
              variant="outlined"
              onClick={handleTestConnection}
              disabled={isTesting}
            >
              {isTesting ? 'Testing...' : 'Test Connection'}
            </Button>
          </Grid>
        </Grid>
      </Box>

      {testResult && (
        <Alert 
          severity={testResult.success ? 'success' : 'error'} 
          sx={{ mt: 3 }}
        >
          {testResult.message}
          {testResult.details && (
            <Box component="pre" sx={{ mt: 1, p: 1, bgcolor: 'background.paper', borderRadius: 1, fontSize: '0.8rem', overflow: 'auto' }}>
              {JSON.stringify(testResult.details, null, 2)}
            </Box>
          )}
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
