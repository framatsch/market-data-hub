import { useQuery } from '@tanstack/react-query';
import { Alert, Box, Chip, CircularProgress, Stack, TextField, Typography } from '@mui/material';
import { fetcher } from '../../lib/api';
import { BUDGET_KEYS, describeSharing, describeUsage, parseBudget, type BudgetKey } from '../../lib/budget';
import type { ProviderUsage } from '../../types';

const LABELS: Record<BudgetKey, string> = {
  request_budget_per_day: 'Requests per day (0 = no limit)',
  request_budget_per_month: 'Requests per month (0 = no limit)',
};

function UsageDisplay({ providerName }: { providerName: string }) {
  const usage = useQuery<ProviderUsage>({
    queryKey: ['providerUsage', providerName],
    queryFn: () => fetcher(`/api/admin/providers/${providerName}/usage`),
    refetchInterval: 30000,
  });
  if (usage.isLoading) return <CircularProgress size={20} />;
  if (usage.error || !usage.data) {
    return <Alert severity="warning">Usage is unavailable: {usage.error?.message ?? 'no data'}</Alert>;
  }
  const { day, month } = usage.data;
  return (
    <Box data-testid="provider-usage" sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
        <Typography variant="body2">Today: <strong>{describeUsage(day)}</strong></Typography>
        <Typography variant="body2" color="text.secondary">
          resets {new Date(day.resets_at).toLocaleString()}
        </Typography>
        <Chip
          size="small"
          variant="outlined"
          color={usage.data.shared ? 'success' : 'warning'}
          label={usage.data.shared ? 'shared' : 'this replica only'}
        />
      </Stack>
      <Typography variant="body2">
        This month: <strong>{describeUsage(month)}</strong>
        <Typography component="span" variant="body2" color="text.secondary">
          {' '}(resets {new Date(month.resets_at).toLocaleString()})
        </Typography>
      </Typography>
      <Typography variant="caption" color="text.secondary">{describeSharing(usage.data)}</Typography>
      {usage.data.day_exhausted && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          The provider reported its daily quota as exhausted; requests are refused until the next day.
        </Alert>
      )}
    </Box>
  );
}

/** Budget inputs and live usage of a metered provider (shared by all its capabilities). */
export function ProviderBudgetSection({
  providerName,
  values,
  onChange,
}: {
  providerName: string;
  values: Record<BudgetKey, string>;
  onChange: (key: BudgetKey, value: string) => void;
}) {
  return (
    <Box data-testid="provider-budget">
      <UsageDisplay providerName={providerName} />
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
        {BUDGET_KEYS.map((key) => {
          const invalid = parseBudget(values[key]) === null;
          return (
            <TextField
              key={key}
              size="small"
              type="number"
              label={LABELS[key]}
              name={key}
              value={values[key]}
              error={invalid}
              helperText={invalid ? 'Enter a whole number, 0 or greater.' : undefined}
              onChange={(e) => onChange(key, e.target.value)}
              slotProps={{ htmlInput: { min: 0, step: 1 } }}
            />
          );
        })}
      </Box>
      <Typography variant="caption" color="text.secondary">
        One budget covers every capability of this provider (prices, earnings, …). A request over the budget is refused before it is sent.
      </Typography>
    </Box>
  );
}
