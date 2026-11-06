import { useState } from 'react';
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
  Tabs,
  Tab
} from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { fetcher } from '../lib/api';
import type { SystemDefaults } from '../types';
import CacheCard from '../components/CacheCard';

interface SettingsProviderCapabilities {
  prices: string[];
  options: string[];
  companies: string[];
  news: string[];
  volatility: string[];
}

type SettingsTab = 'providers' | 'cache';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab: SettingsTab = searchParams.get('tab') === 'cache' ? 'cache' : 'providers';
  const handleTabChange = (_: React.SyntheticEvent, value: SettingsTab) => {
    setSearchParams(value === 'providers' ? {} : { tab: value }, { replace: true });
  };
  const [successMsg, setSuccessMsg] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  // Local state for the form
  const [edits, setDefaults] = useState<SystemDefaults | null>(null);

  const { data: currentDefaults, isLoading: isLoadingDefaults } = useQuery<SystemDefaults>({
    queryKey: ['systemDefaults'],
    queryFn: () => fetcher('/api/admin/settings/defaults'),
  });

  const { data: capabilities, isLoading: isLoadingCapabilities } = useQuery<SettingsProviderCapabilities>({
    queryKey: ['providerCapabilities'],
    queryFn: () => fetcher('/api/admin/settings/capabilities'),
  });

  const defaults = edits ?? {
    default_price_provider: currentDefaults?.default_price_provider || '',
    default_options_provider: currentDefaults?.default_options_provider || '',
    default_company_provider: currentDefaults?.default_company_provider || '',
    default_news_provider: currentDefaults?.default_news_provider || '',
    default_volatility_provider: currentDefaults?.default_volatility_provider || '',
  };

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
    onError: (err) => {
      setErrorMsg(err.message || 'Failed to update settings.');
    }
  });

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

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={activeTab} onChange={handleTabChange} aria-label="Settings sections">
          <Tab label="Providers" value="providers" id="settings-tab-providers" aria-controls="settings-panel-providers" />
          <Tab label="Response Cache" value="cache" id="settings-tab-cache" aria-controls="settings-panel-cache" />
        </Tabs>
      </Box>

      {activeTab === 'providers' && (
        <Box role="tabpanel" id="settings-panel-providers" aria-labelledby="settings-tab-providers">
          <Typography variant="body1" color="text.secondary" sx={{ mb: 2 }}>
            Configure global system defaults. These settings define which provider is used when a specific capability is requested without an explicit provider.
          </Typography>
          <Alert severity="info" sx={{ mb: 2, maxWidth: 900 }}>
            Schwab OAuth requires registering
            {' '}
            <code>/api/admin/schwab/callback</code>
            {' '}
            as the redirect_uri in the Schwab Developer Portal.
          </Alert>

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

              <FormControl fullWidth margin="normal">
                <InputLabel id="volatility-provider-label">Default Volatility Provider</InputLabel>
                <Select
                  labelId="volatility-provider-label"
                  value={defaults.default_volatility_provider || ''}
                  label="Default Volatility Provider"
                  onChange={(e) => setDefaults({ ...defaults, default_volatility_provider: e.target.value })}
                >
                  <MenuItem value=""><em>None</em></MenuItem>
                  {capabilities?.volatility?.map(p => (
                    <MenuItem key={p} value={p}>{p}</MenuItem>
                  ))}
                </Select>
              </FormControl>

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
        </Box>
      )}

      {activeTab === 'cache' && (
        <Box role="tabpanel" id="settings-panel-cache" aria-labelledby="settings-tab-cache">
          <CacheCard />
        </Box>
      )}

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
