import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Box, 
  Typography, 
  Paper, 
  Button, 
  FormControl, 
  InputLabel, 
  Select, 
  MenuItem,
  Snackbar,
  Alert,
  CircularProgress,
  TextField
} from '@mui/material';
import { fetcher } from '../lib/api';
import type { SystemDefaults, ProviderCapabilities } from '../types';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [successMsg, setSuccessMsg] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  // Local state for the form
  const [defaults, setDefaults] = useState<SystemDefaults>({
    default_price_provider: '',
    default_options_provider: '',
    default_company_provider: '',
    default_news_provider: '',
    logo_url: '',
  });

  const { data: currentDefaults, isLoading: isLoadingDefaults } = useQuery<SystemDefaults>({
    queryKey: ['systemDefaults'],
    queryFn: () => fetcher('/api/admin/settings/defaults'),
  });

  const { data: capabilities, isLoading: isLoadingCapabilities } = useQuery<ProviderCapabilities>({
    queryKey: ['providerCapabilities'],
    queryFn: () => fetcher('/api/admin/settings/capabilities'),
  });

  const updateDefaultsMutation = useMutation({
    mutationFn: (newDefaults: SystemDefaults) => 
      fetcher('/api/admin/settings/defaults', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newDefaults),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['systemDefaults'] });
      setSuccessMsg('Settings updated successfully.');
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to update settings.');
    }
  });

  // Sync local state when defaults load
  useEffect(() => {
    if (currentDefaults) {
      setDefaults({
        default_price_provider: currentDefaults.default_price_provider || '',
        default_options_provider: currentDefaults.default_options_provider || '',
        default_company_provider: currentDefaults.default_company_provider || '',
        default_news_provider: currentDefaults.default_news_provider || '',
        logo_url: currentDefaults.logo_url || '',
      });
    }
  }, [currentDefaults]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateDefaultsMutation.mutate(defaults);
  };

  const isLoading = isLoadingDefaults || isLoadingCapabilities;

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Settings
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 2 }}>
        Configure global system defaults. These settings define which provider is used when a specific capability is requested without an explicit provider.
      </Typography>

      <Paper sx={{ p: 3, maxWidth: 600 }}>
        <form onSubmit={handleSubmit}>
          <FormControl fullWidth margin="normal">
            <InputLabel id="price-provider-label">Default Price Provider</InputLabel>
            <Select
              labelId="price-provider-label"
              value={defaults.default_price_provider || ''}
              label="Default Price Provider"
              onChange={(e) => setDefaults({ ...defaults, default_price_provider: e.target.value })}
            >
              <MenuItem value=""><em>None</em></MenuItem>
              {capabilities?.prices?.map(p => (
                <MenuItem key={p} value={p}>{p}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl fullWidth margin="normal">
            <InputLabel id="options-provider-label">Default Options Provider</InputLabel>
            <Select
              labelId="options-provider-label"
              value={defaults.default_options_provider || ''}
              label="Default Options Provider"
              onChange={(e) => setDefaults({ ...defaults, default_options_provider: e.target.value })}
            >
              <MenuItem value=""><em>None</em></MenuItem>
              {capabilities?.options?.map(p => (
                <MenuItem key={p} value={p}>{p}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl fullWidth margin="normal">
            <InputLabel id="company-provider-label">Default Company Provider</InputLabel>
            <Select
              labelId="company-provider-label"
              value={defaults.default_company_provider || ''}
              label="Default Company Provider"
              onChange={(e) => setDefaults({ ...defaults, default_company_provider: e.target.value })}
            >
              <MenuItem value=""><em>None</em></MenuItem>
              {capabilities?.companies?.map(p => (
                <MenuItem key={p} value={p}>{p}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl fullWidth margin="normal">
            <InputLabel id="news-provider-label">Default News Provider</InputLabel>
            <Select
              labelId="news-provider-label"
              value={defaults.default_news_provider || ''}
              label="Default News Provider"
              onChange={(e) => setDefaults({ ...defaults, default_news_provider: e.target.value })}
            >
              <MenuItem value=""><em>None</em></MenuItem>
              {capabilities?.news?.map(p => (
                <MenuItem key={p} value={p}>{p}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            fullWidth
            margin="normal"
            label="Custom Logo URL"
            placeholder="/admin/logo.svg"
            value={defaults.logo_url || ''}
            onChange={(e) => setDefaults({ ...defaults, logo_url: e.target.value })}
            size="small"
            helperText="Path or absolute URL to override the default Market Data Hub logo"
          />

          <Box sx={{ mt: 3, display: 'flex', justifyContent: 'flex-end' }}>
            <Button 
              type="submit" 
              variant="contained" 
              disabled={updateDefaultsMutation.isPending}
            >
              {updateDefaultsMutation.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </Box>
        </form>
      </Paper>

      <Snackbar 
        open={!!successMsg} 
        autoHideDuration={6000} 
        onClose={() => setSuccessMsg('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSuccessMsg('')} severity="success" sx={{ width: '100%' }}>
          {successMsg}
        </Alert>
      </Snackbar>

      <Snackbar 
        open={!!errorMsg} 
        autoHideDuration={6000} 
        onClose={() => setErrorMsg('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setErrorMsg('')} severity="error" sx={{ width: '100%' }}>
          {errorMsg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
