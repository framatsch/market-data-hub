import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Typography,
  Grid,
  Card,
  CardContent,
  CardHeader,
  CardActionArea,
  Chip,
  Box,
  Alert,
  AlertTitle,
  Button,
  Skeleton,
  Drawer,
  Tabs,
  Tab,
  Divider,
  IconButton,
  FormControlLabel,
  Switch,
  Snackbar,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { fetcher } from '../lib/api';
import type { Provider, SchwabAuthStatus } from '../types';
import { ApiKeyAuthSection } from '../components/provider/ApiKeyAuthSection';
import { IbkrConnectionSection } from '../components/provider/IbkrConnectionSection';
import { SchwabOAuthSection } from '../components/provider/SchwabOAuthSection';
import { ProviderConfigSection } from '../components/provider/ProviderConfigSection';

// ─── helpers ───────────────────────────────────────────────────────────────

function statusColor(status: Provider['status']): 'success' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'healthy':   return 'success';
    case 'paused':
    case 'degraded':  return 'warning';
    case 'offline':   return 'error';
    default:          return 'default';
  }
}

function providerLabel(name: string) {
  const labels: Record<string, string> = {
    lseg: 'LSEG',
    ibkr: 'IBKR',
    schwab: 'Schwab',
    finnhub: 'Finnhub',
    polygon: 'Polygon',
    mock: 'Mock',
  };
  return labels[name] ?? name.toUpperCase();
}

function capabilityLabel(capability: string) {
  return capability.charAt(0).toUpperCase() + capability.slice(1);
}

type FilterType = 'all' | 'active' | 'inactive' | 'healthy' | 'not-configured';

interface CredentialMeta {
  provider: string;
  credential_name: string;
  set: boolean;
  value: string | null;
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

// ─── Tab panel ─────────────────────────────────────────────────────────────

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <div role="tabpanel" hidden={value !== index}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

// ─── Auth section per provider ─────────────────────────────────────────────

function AuthSection({ providerName }: { providerName: string }) {
  if (providerName === 'ibkr') {
    return <IbkrConnectionSection />;
  }
  if (providerName === 'schwab') {
    return (
      <>
        <ApiKeyAuthSection
          providerName="schwab"
          visibleCredentials={['api_key', 'app_secret']}
        />
        <SchwabOAuthSection />
      </>
    );
  }
  return <ApiKeyAuthSection providerName={providerName} />;
}

// ─── Provider detail drawer ────────────────────────────────────────────────

function ProviderDrawer({
  provider,
  schwabStatus,
  onClose,
  onToggle,
}: {
  provider: Provider | null;
  schwabStatus: SchwabAuthStatus | undefined;
  onClose: () => void;
  onToggle: (name: string, enabled: boolean) => void;
}) {
  const [tab, setTab] = useState(0);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  // Reset tab when switching providers
  const [lastProvider, setLastProvider] = useState<string | null>(null);
  if (provider && provider.name !== lastProvider) {
    setLastProvider(provider.name);
    setTab(0);
  }

  const showSuccess = (msg: string) => setSnackbar({ open: true, message: msg, severity: 'success' });
  const showError   = (msg: string) => setSnackbar({ open: true, message: msg, severity: 'error' });

  const isMock = provider?.name === 'mock';

  return (
    <Drawer
      anchor="right"
      open={!!provider}
      onClose={onClose}
      slotProps={{ paper: { sx: { width: { xs: '100vw', sm: '520px' } } } }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {provider && (
          <>
            {/* Header */}
            <Box sx={{ px: 3, pt: 3, pb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="h6">{providerLabel(provider.name)}</Typography>
                <IconButton onClick={onClose} size="small">
                  <CloseIcon />
                </IconButton>
              </Box>

              {(provider.capabilities && provider.capabilities.length > 0) && (
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1.5 }}>
                  {provider.capabilities.map(cap => (
                    <Chip key={cap} label={capabilityLabel(cap)} size="small" color="primary" variant="outlined" />
                  ))}
                </Box>
              )}

              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                <Chip

                  label={provider.status.toUpperCase()}
                  color={statusColor(provider.status)}
                  size="small"
                />
                {provider.name === 'schwab' && schwabStatus?.days_remaining !== undefined && (
                  <Chip
                    label={`${schwabStatus.days_remaining}d remaining`}
                    size="small"
                    variant="outlined"
                    color={schwabStatus.days_remaining < 3 ? 'error' : 'default'}
                  />
                )}
                <Box sx={{ ml: 'auto' }}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={provider.enabled}
                        onChange={(e) => onToggle(provider.name, e.target.checked)}
                        disabled={isMock}
                        size="small"
                      />
                    }
                    label="Enabled"
                    sx={{ mr: 0 }}
                  />
                </Box>
              </Box>

              {provider.error && (
                <Alert severity="error" sx={{ mt: 1 }}>
                  {provider.error}
                </Alert>
              )}
            </Box>

            <Divider />

            {/* Tabs */}
            {isMock ? (
              <Box sx={{ px: 3, pt: 3 }}>
                <Typography color="text.secondary">No configuration required for Mock provider.</Typography>
              </Box>
            ) : (
              <>
                <Box sx={{ px: 3, borderBottom: 1, borderColor: 'divider' }}>
                  <Tabs value={tab} onChange={(_, v) => setTab(v)}>
                    <Tab label="Auth" id="tab-auth" />
                    <Tab label="Configuration" id="tab-config" />
                  </Tabs>
                </Box>

                <Box sx={{ flex: 1, overflow: 'auto', px: 3 }}>
                  <TabPanel value={tab} index={0}>
                    <AuthSection providerName={provider.name} />
                  </TabPanel>

                  <TabPanel value={tab} index={1}>
                    <ProviderConfigSection
                      providerName={provider.name}
                      hideConnectionJson={provider.name === 'ibkr'}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  </TabPanel>
                </Box>
              </>
            )}
          </>
        )}

        <Snackbar
          open={snackbar.open}
          autoHideDuration={6000}
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        >
          <Alert
            onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
            severity={snackbar.severity}
          >
            {snackbar.message}
          </Alert>
        </Snackbar>
      </Box>
    </Drawer>
  );
}

// ─── Provider card ─────────────────────────────────────────────────────────

function ProviderCard({
  provider,
  schwabStatus,
  onClick,
}: {
  provider: Provider;
  schwabStatus?: SchwabAuthStatus;
  onClick: () => void;
}) {
  const timeout    = provider.config_summary?.timeout_seconds  ?? provider.config?.timeout_seconds;
  const retries    = provider.config_summary?.retry_count       ?? provider.config?.retry_count;
  const rateLimit  = provider.config_summary?.rate_limit_per_sec ?? provider.config?.rate_limit_per_sec;
  const capabilities = provider.capabilities ?? [];

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardActionArea onClick={onClick} sx={{ flex: 1 }}>
        <CardHeader
          title={providerLabel(provider.name)}
          subheader={
            capabilities.length > 0 ? (
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                {capabilities.map(cap => (
                  <Chip key={cap} label={capabilityLabel(cap)} size="small" color="primary" variant="outlined" />
                ))}
              </Box>
            ) : null
          }
          action={
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 0.5, pt: 0.5 }}>
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Chip
                  label={provider.status.toUpperCase()}
                  color={statusColor(provider.status)}
                  size="small"
                />
              </Box>
              {provider.name === 'schwab' && schwabStatus?.days_remaining !== undefined && (
                <Chip
                  label={`${schwabStatus.days_remaining}d`}
                  size="small"
                  variant="outlined"
                  color={schwabStatus.days_remaining < 3 ? 'error' : 'default'}
                />
              )}
            </Box>
          }
        />
        <CardContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            <Typography variant="caption" color="text.secondary">
              Timeout: {timeout != null ? `${timeout}s` : 'N/A'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Retries: {retries ?? 'N/A'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Rate limit: {rateLimit != null ? `${rateLimit}/s` : 'N/A'}
            </Typography>
          </Box>
          {provider.error && (
            <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
              {provider.error}
            </Typography>
          )}
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

// ─── Dashboard page ────────────────────────────────────────────────────────

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [activeFilters, setActiveFilters] = useState<Set<FilterType>>(new Set(['all']));
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const providersQuery = useQuery<Provider[]>({
    queryKey: ['providers'],
    queryFn: () => fetcher('/api/admin/providers'),
    refetchInterval: 30000,
  });

  const credentialsQuery = useQuery<CredentialMeta[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
  });

  const schwabStatusQuery = useQuery<SchwabAuthStatus>({
    queryKey: ['schwab', 'status'],
    queryFn: () => fetcher('/api/admin/schwab/auth/status'),
    refetchInterval: 60000,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      fetcher(`/api/admin/providers/${name}/${enabled ? 'enable' : 'disable'}`, { method: 'POST' }),
    onMutate: async ({ name, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ['providers'] });
      const prev = queryClient.getQueryData<Provider[]>(['providers']);
      queryClient.setQueryData<Provider[]>(['providers'], (old) =>
        old?.map((p) => (p.name === name ? { ...p, enabled } : p))
      );
      // keep drawer in sync
      setSelectedProvider((s) => (s?.name === name ? { ...s, enabled } : s));
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      queryClient.setQueryData(['providers'], ctx?.prev);
      setSnackbar({ open: true, message: 'Failed to update provider', severity: 'error' });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setSnackbar({ open: true, message: 'Provider status updated', severity: 'success' });
    },
  });

  const handleToggle = (name: string, enabled: boolean) => {
    toggleMutation.mutate({ name, enabled });
  };

  const handleCardClick = (provider: Provider) => {
    setSelectedProvider(provider);
  };

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

  const filteredProviders = providersQuery.data
    ? filterProviders(providersQuery.data, activeFilters, credentialsQuery.data)
    : [];

  const schwabStatus = schwabStatusQuery.data;
  const showSchwabAlert =
    schwabStatus && (schwabStatus.status === 'expired' || schwabStatus.paused);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Providers
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 3 }}>
        {(['all', 'active', 'inactive', 'healthy', 'not-configured'] as FilterType[]).map(filter => (
          <Chip
            key={filter}
            label={filter.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
            onClick={() => toggleFilter(filter)}
            color={activeFilters.has(filter) ? 'primary' : 'default'}
            variant={activeFilters.has(filter) ? 'filled' : 'outlined'}
          />
        ))}
      </Box>

      {showSchwabAlert && (
        <Alert
          severity="warning"
          sx={{ mb: 3 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                const schwab = providersQuery.data?.find((p) => p.name === 'schwab');
                if (schwab) setSelectedProvider(schwab);
              }}
            >
              Re-authorize
            </Button>
          }
        >
          <AlertTitle>Schwab Authorization Required</AlertTitle>
          {schwabStatus.status === 'expired'
            ? 'Your Schwab API token has expired.'
            : 'Schwab provider is paused due to authorization issues.'}
        </Alert>
      )}

      <Grid container spacing={3}>
        {providersQuery.isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Grid size={{ xs: 12, sm: 6, md: 4 }} key={i}>
                <Skeleton variant="rectangular" height={180} sx={{ borderRadius: 3 }} />
              </Grid>
            ))
          : filteredProviders.length === 0 ? (
              <Grid size={{ xs: 12 }}>
                <Typography color="text.secondary">No providers match the selected filters</Typography>
              </Grid>
            ) : filteredProviders.map((provider) => (
              <Grid size={{ xs: 12, sm: 6, md: 4 }} key={provider.name}>
                <ProviderCard
                  provider={provider}
                  schwabStatus={provider.name === 'schwab' ? schwabStatus : undefined}
                  onClick={() => handleCardClick(provider)}
                />
              </Grid>
            ))}
      </Grid>

      <ProviderDrawer
        provider={selectedProvider}
        schwabStatus={schwabStatus}
        onClose={() => setSelectedProvider(null)}
        onToggle={handleToggle}
      />

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity={snackbar.severity}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
