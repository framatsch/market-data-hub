import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  TextField,
  Button,
  Grid,
  CircularProgress,
  Divider,
  Typography,
  Switch,
  FormControlLabel,
} from '@mui/material';
import { fetcher } from '../../lib/api';
import type { ProviderConfig } from '../../types';

export function ProviderConfigSection({
  providerName,
  hideConnectionJson = false,
  onSuccess,
  onError,
}: {
  providerName: string;
  hideConnectionJson?: boolean;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const configQuery = useQuery<ProviderConfig>({
    queryKey: ['providerConfig', providerName],
    queryFn: () => fetcher(`/api/admin/providers/${providerName}/config`),
  });

  const [formData, setFormData] = useState<Partial<ProviderConfig>>({});
  const [connectionConfigText, setConnectionConfigText] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!configQuery.data) {
      return;
    }
    setFormData(configQuery.data);
    setConnectionConfigText(
      configQuery.data.connection_config
        ? JSON.stringify(configQuery.data.connection_config, null, 2)
        : ''
    );
  }, [configQuery.data]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : type === 'number' ? Number(value) : value,
    }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const payload: Record<string, unknown> = {
        enabled: formData.enabled,
        timeout_seconds: formData.timeout_seconds,
        retry_count: formData.retry_count,
        retry_backoff_seconds: formData.retry_backoff_seconds,
        rate_limit_per_sec: formData.rate_limit_per_sec,
        circuit_breaker_enabled: formData.circuit_breaker_enabled,
        circuit_breaker_failure_threshold: formData.circuit_breaker_failure_threshold,
        circuit_breaker_reset_seconds: formData.circuit_breaker_reset_seconds,
      };

      if (!hideConnectionJson) {
        if (connectionConfigText.trim()) {
          try {
            payload.connection_config = JSON.parse(connectionConfigText);
          } catch {
            onError('Connection Config must be valid JSON');
            setIsSaving(false);
            return;
          }
        } else {
          payload.connection_config = {};
        }
      }

      await fetcher(`/api/admin/providers/${providerName}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      onSuccess(`${providerName.toUpperCase()} config saved`);
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      queryClient.invalidateQueries({ queryKey: ['providerConfig', providerName] });
    } catch (err: any) {
      onError(`Failed to save config: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  if (configQuery.isLoading) return <CircularProgress size={24} />;

  return (
    <Box component="form" onSubmit={handleSave}>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Timeout (seconds)"
            name="timeout_seconds"
            type="number"
            value={formData.timeout_seconds || ''}
            onChange={handleChange}
            size="small"
            required
            slotProps={{ htmlInput: { min: 1 } }}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Retry Count"
            name="retry_count"
            type="number"
            value={formData.retry_count ?? ''}
            onChange={handleChange}
            size="small"
            required
            slotProps={{ htmlInput: { min: 0 } }}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Retry Backoff (seconds)"
            name="retry_backoff_seconds"
            type="number"
            value={formData.retry_backoff_seconds || ''}
            onChange={handleChange}
            size="small"
            required
            slotProps={{ htmlInput: { min: 0 } }}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Rate Limit (per sec)"
            name="rate_limit_per_sec"
            type="number"
            value={formData.rate_limit_per_sec || ''}
            onChange={handleChange}
            size="small"
            required
            slotProps={{ htmlInput: { min: 0.1, step: 0.1 } }}
          />
        </Grid>

        <Grid size={{ xs: 12 }}>
          <Divider sx={{ my: 1 }} />
          <Typography variant="subtitle2" gutterBottom>Circuit Breaker</Typography>
        </Grid>

        <Grid size={{ xs: 12 }}>
          <FormControlLabel
            control={
              <Switch
                name="circuit_breaker_enabled"
                checked={!!formData.circuit_breaker_enabled}
                onChange={handleChange}
              />
            }
            label="Enabled"
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Failure Threshold"
            name="circuit_breaker_failure_threshold"
            type="number"
            value={formData.circuit_breaker_failure_threshold || ''}
            onChange={handleChange}
            size="small"
            disabled={!formData.circuit_breaker_enabled}
            slotProps={{ htmlInput: { min: 1 } }}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <TextField
            fullWidth
            label="Reset Seconds"
            name="circuit_breaker_reset_seconds"
            type="number"
            value={formData.circuit_breaker_reset_seconds || ''}
            onChange={handleChange}
            size="small"
            disabled={!formData.circuit_breaker_enabled}
            slotProps={{ htmlInput: { min: 1 } }}
          />
        </Grid>

        {!hideConnectionJson && (
          <Grid size={{ xs: 12 }}>
            <Divider sx={{ my: 1 }} />
            <Typography variant="subtitle2" gutterBottom>Connection Config (JSON)</Typography>
            <TextField
              fullWidth
              multiline
              rows={4}
              name="connection_config"
              value={connectionConfigText}
              onChange={(e) => setConnectionConfigText(e.target.value)}
              size="small"
              placeholder='{"host": "localhost", "port": 4001}'
            />
          </Grid>
        )}

        <Grid size={{ xs: 12 }} sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            type="submit"
            variant="contained"
            disabled={isSaving}
          >
            {isSaving ? 'Saving...' : 'Save Configuration'}
          </Button>
        </Grid>
      </Grid>
    </Box>
  );
}
