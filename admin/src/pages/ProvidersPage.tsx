import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  Typography,
  Box,
  CircularProgress,
  Stack,
  Snackbar,
  Alert,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Collapse,
  Switch,
  Tooltip,
} from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import { fetcher } from '../lib/api';
import type { Provider } from '../types';
import { ProviderDetailsPanel } from '../components/provider/ProviderDetailsPanel';
import { ApiKeyAuthSection } from '../components/provider/ApiKeyAuthSection';
import { IbkrConnectionSection } from '../components/provider/IbkrConnectionSection';
import { SchwabOAuthSection } from '../components/provider/SchwabOAuthSection';

type FilterType = 'all' | 'active' | 'inactive' | 'healthy' | 'not-configured';

interface CredentialMeta {
  provider: string;
  credential_name: string;
  set: boolean;
  masked_value: string | null;
  updated_at: string | null;
}

function filterProviders(providers: Provider[], activeFilters: Set<FilterType>, credentials: CredentialMeta[] | undefined) {
  if (activeFilters.has('all')) return providers;

  return providers.filter(provider => {
    let match = false;
    if (activeFilters.has('active') && provider.enabled) match = true;
    if (activeFilters.has('inactive') && !provider.enabled) match = true;
    if (activeFilters.has('healthy') && provider.status === 'healthy') match = true;

    if (activeFilters.has('not-configured')) {
      if (provider.name === 'mock' || provider.name === 'prixe') {
        // never match
      } else if (provider.name === 'ibkr') {
        if (provider.connection_config?.account_id === 'DU123456') {
          match = true;
        }
      } else {
        const providerCreds = credentials?.filter(c => c.provider === provider.name) || [];
        if (providerCreds.length > 0 && providerCreds.every(c => !c.set)) {
          match = true;
        }
      }
    }
    return match;
  });
}

function statusColor(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'paused') return 'warning';
  if (status === 'disabled') return 'default';
  return 'error';
}

function capabilityLabel(capability: string) {
  return capability.charAt(0).toUpperCase() + capability.slice(1);
}

function renderAuthSection(provider: Provider) {
  if (provider.name === 'schwab') {
    return (
      <>
        <ApiKeyAuthSection providerName="schwab" visibleCredentials={["api_key", "app_secret"]} />
        <SchwabOAuthSection />
      </>
    );
  }
  if (provider.name === 'ibkr') {
    return <IbkrConnectionSection />;
  }
  return <ApiKeyAuthSection providerName={provider.name} />;
}

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const [activeFilters, setActiveFilters] = useState<Set<FilterType>>(new Set(['all']));
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);

  const providersQuery = useQuery<Provider[]>({
    queryKey: ['providers'],
    queryFn: () => fetcher('/api/admin/providers'),
  });

  const credentialsQuery = useQuery<CredentialMeta[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
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

  // Auto-expand from ?expand= URL param
  useEffect(() => {
    const expandParam = searchParams.get('expand');
    if (expandParam) {
      setExpandedProvider(expandParam);
    }
  }, [searchParams]);

  const toggleFilter = (filter: FilterType) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (filter === 'all') return new Set(['all']);
      next.delete('all');
      if (next.has(filter)) {
        next.delete(filter);
      } else {
        next.add(filter);
      }
      if (next.size === 0) return new Set(['all']);
      return next;
    });
  };

  const handleRowClick = (providerName: string) => {
    setExpandedProvider(prev => (prev === providerName ? null : providerName));
  };

  const filteredProviders = providersQuery.data
    ? filterProviders(providersQuery.data, activeFilters, credentialsQuery.data)
    : [];

  const expandParam = searchParams.get('expand');

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Provider Management
      </Typography>

      {/* 0.6: Filter chips above the list */}
      <Stack direction="row" spacing={1} sx={{ mt: 2, mb: 3 }}>
        {(['all', 'active', 'inactive', 'healthy', 'not-configured'] as FilterType[]).map(filter => (
          <Chip
            key={filter}
            label={filter.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
            onClick={() => toggleFilter(filter)}
            color={activeFilters.has(filter) ? 'primary' : 'default'}
            variant={activeFilters.has(filter) ? 'filled' : 'outlined'}
          />
        ))}
      </Stack>

      {providersQuery.isLoading ? (
        <CircularProgress />
      ) : filteredProviders.length === 0 ? (
        <Typography color="text.secondary">No providers match the selected filters</Typography>
      ) : (
        // 0.1: Table/card list view
        <TableContainer component={Paper} variant="outlined">
          <Table size="medium">
            <TableHead>
              <TableRow>
                <TableCell width={48} />
                <TableCell><Typography variant="subtitle2">Provider</Typography></TableCell>
                <TableCell><Typography variant="subtitle2">Capabilities</Typography></TableCell>
                <TableCell><Typography variant="subtitle2">Status</Typography></TableCell>
                <TableCell align="right"><Typography variant="subtitle2">Enabled</Typography></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredProviders.map((provider) => {
                const isOpen = expandedProvider === provider.name;
                const isAutoExpand = expandParam === provider.name;
                const capabilities = provider.capabilities ?? [];
                return (
                  <>
                    {/* Provider row */}
                    <TableRow
                      key={provider.name}
                      hover
                      onClick={() => handleRowClick(provider.name)}
                      sx={{ cursor: 'pointer', '& > *': { borderBottom: isOpen ? 'none' : undefined } }}
                    >
                      <TableCell>
                        <IconButton size="small" aria-label="expand row">
                          {isOpen ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
                        </IconButton>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body1" sx={{ fontWeight: 600 }}>
                          {provider.name.toUpperCase()}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {capabilities.map(capabilityLabel).join(' · ')}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                          {capabilities.map(cap => (
                            <Chip key={cap} label={capabilityLabel(cap)} size="small" variant="outlined" />
                          ))}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={provider.status ?? 'unknown'}
                          color={statusColor(provider.status ?? '')}
                          size="small"
                          variant="filled"
                        />
                      </TableCell>
                      <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                        <Tooltip title={provider.enabled ? 'Disable provider' : 'Enable provider'}>
                          <Switch
                            checked={provider.enabled}
                            onChange={(e) => toggleMutation.mutate({ name: provider.name, enabled: e.target.checked })}
                            size="small"
                          />
                        </Tooltip>
                      </TableCell>
                    </TableRow>

                    {/* 0.2: Inline detail panel row */}
                    <TableRow key={`${provider.name}-detail`}>
                      <TableCell colSpan={5} sx={{ p: 0, border: 0 }}>
                        <Collapse in={isOpen} timeout="auto" unmountOnExit>
                          <Box sx={{ p: 3, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>
                            <ProviderDetailsPanel
                              providerName={provider.name}
                              enabled={provider.enabled}
                              hideConnectionJson={provider.name === 'ibkr'}
                              authSection={renderAuthSection(provider)}
                              onSuccess={(msg) => setSnackbar({ open: true, message: msg, severity: 'success' })}
                              onError={(msg) => setSnackbar({ open: true, message: msg, severity: 'error' })}
                              onToggle={(enabled) => toggleMutation.mutate({ name: provider.name, enabled })}
                              defaultTab={isAutoExpand ? 0 : 0}
                            />
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

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
