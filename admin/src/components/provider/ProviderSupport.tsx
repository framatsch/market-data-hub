import { Box, Chip, Typography } from '@mui/material';
import type { Provider } from '../../types';

function Row({ label, types }: { label: string; types: string[] }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 140 }}>
        {label}
      </Typography>
      {types.length > 0 ? (
        types.map((type) => <Chip key={type} label={type} size="small" variant="outlined" />)
      ) : (
        <Typography variant="caption" color="text.secondary">
          none
        </Typography>
      )}
    </Box>
  );
}

/** Instrument types the hub has implemented per provider (not subscription state). */
export function ProviderSupport({ provider }: { provider: Provider }) {
  const { price_support, options_support, volatility_support } = provider;
  if (!price_support && !options_support && !volatility_support) return null;

  return (
    <Box
      data-testid="provider-support"
      sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, my: 1.5 }}
    >
      <Typography variant="subtitle2">Implemented instrument types</Typography>
      {price_support && (
        <>
          <Row label="Last price" types={price_support.price_sec_types} />
          <Row label="Price history" types={price_support.price_history_sec_types} />
        </>
      )}
      {options_support && (
        <Row label="Option underlyings" types={options_support.option_underlying_sec_types} />
      )}
      {volatility_support && (
        <>
          <Row label="Volatility" types={volatility_support.volatility_sec_types} />
          <Row
            label="Volatility history"
            types={volatility_support.volatility_history_sec_types}
          />
        </>
      )}
    </Box>
  );
}
