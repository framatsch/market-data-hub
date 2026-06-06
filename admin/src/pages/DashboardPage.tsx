import { useQuery } from '@tanstack/react-query';
import {
  Typography,
  Grid,
  Card,
  CardContent,
  CardHeader,
  Chip,
  Box,
  Alert,
  AlertTitle,
  Button,
  Skeleton,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { fetcher } from '../lib/api';
import type { Provider, SchwabStatus } from '../types';

export default function DashboardPage() {
  const navigate = useNavigate();

  const providersQuery = useQuery<Provider[]>({
    queryKey: ['providers'],
    queryFn: () => fetcher('/api/admin/providers'),
    refetchInterval: 30000,
  });

  const schwabStatusQuery = useQuery<SchwabStatus>({
    queryKey: ['schwab', 'status'],
    queryFn: () => fetcher('/api/admin/schwab/auth/status'),
    refetchInterval: 60000,
  });

  const getStatusColor = (status: Provider['status']) => {
    switch (status) {
      case 'healthy':
        return 'success';
      case 'paused':
      case 'degraded':
        return 'warning';
      case 'offline':
        return 'error';
      default:
        return 'default';
    }
  };

  const getConfigValue = (
    provider: Provider,
    key: 'timeout_seconds' | 'retry_count' | 'rate_limit_per_sec'
  ) => provider.config_summary?.[key] ?? provider.config?.[key];

  const isLoading = providersQuery.isLoading || schwabStatusQuery.isLoading;
  const isError = providersQuery.isError;

  if (isError) {
    return (
      <Alert severity="error">
        <AlertTitle>Error</AlertTitle>
        Failed to fetch provider status. Please check your connection and try again.
      </Alert>
    );
  }

  const schwabAlert = schwabStatusQuery.data && 
    (schwabStatusQuery.data.status === 'expired' || schwabStatusQuery.data.paused) ? (
      <Alert
        severity="warning"
        sx={{ mb: 3 }}
        action={
          <Button color="inherit" size="small" onClick={() => navigate('/admin/schwab-auth')}>
            Re-authorize
          </Button>
        }
      >
        <AlertTitle>Schwab Authorization Required</AlertTitle>
        {schwabStatusQuery.data.status === 'expired' 
          ? 'Your Schwab API token has expired.' 
          : 'Schwab provider is paused due to authorization issues.'}
      </Alert>
    ) : null;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Dashboard
      </Typography>

      {schwabAlert}

      <Grid container spacing={3}>
        {isLoading
          ? Array.from(new Array(3)).map((_, index) => (
              <Grid size={{ xs: 12, md: 4 }} key={index}>
                <Skeleton variant="rectangular" height={200} sx={{ borderRadius: 3 }} />
              </Grid>
            ))
          : providersQuery.data?.map((provider) => {
              const timeout = getConfigValue(provider, 'timeout_seconds');
              const retries = getConfigValue(provider, 'retry_count');
              const rateLimit = getConfigValue(provider, 'rate_limit_per_sec');

              return (<Grid size={{ xs: 12, md: 4 }} key={provider.name}>
                <Card>
                  <CardHeader
                    title={provider.name.toUpperCase()}
                    action={
                      <Chip
                        label={provider.status.toUpperCase()}
                        color={getStatusColor(provider.status)}
                        size="small"
                      />
                    }
                  />
                  <CardContent>
                    <Box sx={{ mb: 2 }}>
                      <Typography variant="body2" color="text.secondary">
                        Enabled: {provider.enabled ? 'Yes' : 'No'}
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" sx={{ display: 'block' }}>
                        Timeout: {timeout ?? 'N/A'}{typeof timeout === 'number' ? 's' : ''}
                      </Typography>
                      <Typography variant="caption" sx={{ display: 'block' }}>
                        Retries: {retries ?? 'N/A'}
                      </Typography>
                      <Typography variant="caption" sx={{ display: 'block' }}>
                        Rate Limit: {rateLimit ?? 'N/A'}{typeof rateLimit === 'number' ? '/s' : ''}
                      </Typography>
                    </Box>
                    {provider.name === 'schwab' && schwabStatusQuery.data?.days_remaining !== undefined && (
                      <Box sx={{ mt: 2 }}>
                        <Chip
                          label={`${schwabStatusQuery.data.days_remaining} days left`}
                          variant="outlined"
                          size="small"
                          color={schwabStatusQuery.data.days_remaining < 3 ? 'error' : 'default'}
                        />
                      </Box>
                    )}
                    {provider.error && (
                      <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
                        {provider.error}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              </Grid>);
            })}
      </Grid>
    </Box>
  );
}
