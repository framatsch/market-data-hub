import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Typography,
  Box,
  Switch,
  FormControlLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  TextField,
  Button,
  Grid,
  Snackbar,
  Alert,
  CircularProgress,
  Stack,
  Divider,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { fetcher } from '../lib/api';
import type { Provider, ProviderConfig } from '../types';

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const providersQuery = useQuery<Provider[]>({
    queryKey: ['providers'],
    queryFn: () => fetcher('/api/admin/providers'),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      fetcher(`/api/admin/providers/${name}/${enabled ? 'enable' : 'disable'}`, { method: 'POST' }),
    onMutate: async ({ name, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ['providers'] });
      const previousProviders = queryClient.getQueryData<Provider[]>(['providers']);
      queryClient.setQueryData<Provider[]>(['providers'], (old) =>
        old?.map((p) => (p.name === name ? { ...p, enabled } : p))
      );
      return { previousProviders };
    },
    onError: (err, _variables, context) => {
      queryClient.setQueryData(['providers'], context?.previousProviders);
      setSnackbar({ open: true, message: `Failed to update provider: ${err.message}`, severity: 'error' });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setSnackbar({ open: true, message: 'Provider status updated', severity: 'success' });
    },
  });

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Provider Management
      </Typography>

      <Stack spacing={3} sx={{ mt: 3 }}>
        {providersQuery.isLoading ? (
          <CircularProgress />
        ) : (
          providersQuery.data?.map((provider) => (
            <ProviderSection
              key={provider.name}
              provider={provider}
              onToggle={(enabled) => toggleMutation.mutate({ name: provider.name, enabled })}
              onSuccess={(msg) => setSnackbar({ open: true, message: msg, severity: 'success' })}
              onError={(msg) => setSnackbar({ open: true, message: msg, severity: 'error' })}
            />
          ))
        )}
      </Stack>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert onClose={() => setSnackbar({ ...snackbar, open: false })} severity={snackbar.severity}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

function ProviderSection({
  provider,
  onToggle,
  onSuccess,
  onError,
}: {
  provider: Provider;
  onToggle: (enabled: boolean) => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Accordion expanded={expanded} onChange={() => setExpanded(!expanded)}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', pr: 2 }}>
          <Typography sx={{ flexGrow: 1, fontWeight: 600 }}>
            {provider.name.toUpperCase()}
          </Typography>
          <FormControlLabel
            control={
              <Switch
                checked={provider.enabled}
                onChange={(e) => {
                  e.stopPropagation();
                  onToggle(e.target.checked);
                }}
                onClick={(e) => e.stopPropagation()}
              />
            }
            label={provider.enabled ? 'Enabled' : 'Disabled'}
          />
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Divider sx={{ mb: 2 }} />
        {expanded && (
          <ProviderConfigForm
            name={provider.name}
            onSuccess={onSuccess}
            onError={onError}
          />
        )}
      </AccordionDetails>
    </Accordion>
  );
}

function ProviderConfigForm({
  name,
  onSuccess,
  onError,
}: {
  name: string;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const configQuery = useQuery<ProviderConfig>({
    queryKey: ['providerConfig', name],
    queryFn: () => fetcher(`/api/admin/providers/${name}/config`),
  });

  const [formData, setFormData] = useState<Partial<ProviderConfig>>({});
  const [isSaving, setIsSaving] = useState(false);

  // Initialize form data when query completes
  if (configQuery.data && Object.keys(formData).length === 0) {
    setFormData(configQuery.data);
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : type === 'number' ? parseFloat(value) : value,
    }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await fetcher(`/api/admin/providers/${name}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      onSuccess(`${name.toUpperCase()} config saved`);
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      queryClient.invalidateQueries({ queryKey: ['providerConfig', name] });
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

        <Grid size={12}>
          <Divider sx={{ my: 1 }} />
          <Typography variant="subtitle2" gutterBottom>Circuit Breaker</Typography>
        </Grid>

        <Grid size={12}>
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

        <Grid size={12}>
          <Divider sx={{ my: 1 }} />
          <Typography variant="subtitle2" gutterBottom>Connection Config (JSON)</Typography>
          <TextField
            fullWidth
            multiline
            rows={4}
            name="connection_config_json"
            value={formData.connection_config_json || ''}
            onChange={handleChange}
            size="small"
            placeholder='{"host": "localhost", "port": 4001}'
          />
        </Grid>

        <Grid size={12} sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
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
