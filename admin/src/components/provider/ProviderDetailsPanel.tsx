import React, { useEffect, useState } from 'react';
import { Box, Tabs, Tab, Typography, Chip, Stack, Switch, Tooltip } from '@mui/material';
import { ProviderConfigSection } from './ProviderConfigSection';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function CustomTabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`provider-tabpanel-${index}`}
      aria-labelledby={`provider-tab-${index}`}
      {...other}
    >
      {value === index && (
        <Box sx={{ pt: 3 }}>
          {children}
        </Box>
      )}
    </div>
  );
}

export function ProviderDetailsPanel({
  providerName,
  enabled,
  authSection,
  hideConnectionJson = false,
  onSuccess,
  onError,
  onToggle,
  defaultTab = 0,
}: {
  providerName: string;
  enabled: boolean;
  authSection: React.ReactNode;
  hideConnectionJson?: boolean;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
  onToggle?: (enabled: boolean) => void;
  defaultTab?: number;
}) {
  const [value, setValue] = useState(defaultTab);

  useEffect(() => {
    setValue(defaultTab);
  }, [defaultTab]);

  const handleChange = (_event: React.SyntheticEvent, newValue: number) => {
    setValue(newValue);
  };

  return (
    <Box sx={{ width: '100%' }}>
      {/* Header: provider name + enabled/disabled badge top-right */}
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>
          {providerName.toUpperCase()}
        </Typography>
        <Stack direction="row" sx={{ alignItems: 'center' }} spacing={1}>
          <Chip
            label={enabled ? 'Enabled' : 'Disabled'}
            color={enabled ? 'success' : 'default'}
            size="small"
            variant={enabled ? 'filled' : 'outlined'}
          />
          {onToggle && (
            <Tooltip title={enabled ? 'Disable provider' : 'Enable provider'}>
              <Switch
                checked={enabled}
                onChange={(e) => onToggle(e.target.checked)}
                size="small"
              />
            </Tooltip>
          )}
        </Stack>
      </Stack>

      {/* Tabs: Tab 0 = Auth, Tab 1 = Configuration */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={value} onChange={handleChange} aria-label="provider tabs">
          <Tab label="Auth" id="provider-tab-0" aria-controls="provider-tabpanel-0" />
          <Tab label="Configuration" id="provider-tab-1" aria-controls="provider-tabpanel-1" />
        </Tabs>
      </Box>

      {/* Tab 0: Auth */}
      <CustomTabPanel value={value} index={0}>
        {authSection}
      </CustomTabPanel>

      {/* Tab 1: Configuration */}
      <CustomTabPanel value={value} index={1}>
        <ProviderConfigSection
          providerName={providerName}
          hideConnectionJson={hideConnectionJson}
          onSuccess={onSuccess}
          onError={onError}
        />
      </CustomTabPanel>
    </Box>
  );
}
