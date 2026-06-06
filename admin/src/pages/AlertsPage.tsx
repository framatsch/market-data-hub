import { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Typography,
  Box,
  TextField,
  Button,
  Snackbar,
  Alert,
  CircularProgress,
  Paper,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Stack,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import { fetcher } from '../lib/api';
import type { CredentialMetadata } from '../types';

interface WebhookConfig {
  webhook_url: string;
  format: string;
}

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookFormat, setWebhookFormat] = useState('slack');
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const credentialsQuery = useQuery<CredentialMetadata[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
  });

  const webhookQuery = useQuery<WebhookConfig>({
    queryKey: ['webhookConfig'],
    queryFn: () => fetcher('/api/admin/alerts/webhook'),
  });

  // Pre-fill fields from backend config
  useEffect(() => {
    if (webhookQuery.data) {
      setWebhookUrl(webhookQuery.data.webhook_url || '');
      setWebhookFormat(webhookQuery.data.format || 'slack');
    }
  }, [webhookQuery.data]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await fetcher('/api/admin/alerts/webhook', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          webhook_url: webhookUrl,
          format: webhookFormat,
        }),
      });
      setSnackbar({ open: true, message: 'Alert configuration saved', severity: 'success' });
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      queryClient.invalidateQueries({ queryKey: ['webhookConfig'] });
    } catch (err: any) {
      setSnackbar({ open: true, message: `Failed to save: ${err.message}`, severity: 'error' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    try {
      await fetcher('/api/admin/alerts/test', { method: 'POST' });
      setSnackbar({ open: true, message: 'Test alert sent successfully!', severity: 'success' });
    } catch (err: any) {
      setSnackbar({ open: true, message: `Test failed: ${err.message}`, severity: 'error' });
    } finally {
      setIsTesting(false);
    }
  };

  const isLoading = credentialsQuery.isLoading || webhookQuery.isLoading;

  if (isLoading) return <CircularProgress />;

  const isConfigured = credentialsQuery.data?.some(
    (c) => c.provider_name === 'schwab' && c.credential_name === 'alert_webhook_url' && c.set
  );

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Alert Configuration
      </Typography>
      <Typography variant="body1" sx={{ mb: 4 }}>
        Configure where to receive notifications for Schwab token expiry and system alerts.
      </Typography>

      {!isConfigured && (
        <Alert severity="info" sx={{ mb: 4 }}>
          No webhook is currently configured. Configure one below to receive Schwab token expiry notifications.
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 4, maxWidth: 600 }}>
        <Stack spacing={3}>
          <Typography variant="h6">Schwab Webhook</Typography>
          <TextField
            fullWidth
            label="Webhook URL"
            placeholder="https://hooks.slack.com/services/... or https://discord.com/api/webhooks/..."
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            size="small"
            helperText="The full URL for your Slack, Discord, or Generic JSON webhook"
          />
          <FormControl fullWidth size="small">
            <InputLabel>Notification Format</InputLabel>
            <Select
              value={webhookFormat}
              label="Notification Format"
              onChange={(e) => setWebhookFormat((e.target.value as string))}
            >
              <MenuItem value="slack">Slack (Incoming Webhook)</MenuItem>
              <MenuItem value="discord">Discord (Incoming Webhook)</MenuItem>
              <MenuItem value="generic">Generic JSON</MenuItem>
            </Select>
          </FormControl>
          
          <Box sx={{ display: 'flex', gap: 2, pt: 2 }}>
            <Button
              variant="contained"
              onClick={handleSave}
              disabled={isSaving || !webhookUrl}
            >
              {isSaving ? 'Saving...' : 'Save Configuration'}
            </Button>
            <Button
              variant="outlined"
              startIcon={<SendIcon />}
              onClick={handleTest}
              disabled={isTesting || !isConfigured}
            >
              {isTesting ? 'Sending...' : 'Send Test Alert'}
            </Button>
          </Box>
        </Stack>
      </Paper>

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
