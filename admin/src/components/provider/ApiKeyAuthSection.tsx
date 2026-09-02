import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  TextField,
  Button,
  Grid,
  CircularProgress,
  Typography,
  Chip,
  Alert,
  Snackbar,
  InputAdornment,
  IconButton,
} from '@mui/material';
import { Visibility, VisibilityOff } from '@mui/icons-material';
import { fetcher } from '../../lib/api';
import type { CredentialMetadata, CredentialReveal } from '../../types';

/** Rendered in place of a configured-but-unrevealed secret. */
const MASK = '\u2022'.repeat(12);

export function ApiKeyAuthSection({
  providerName,
  visibleCredentials,
}: {
  providerName: string;
  visibleCredentials?: string[];
}) {
  const queryClient = useQueryClient();
  const credentialsQuery = useQuery<CredentialMetadata[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
  });

  const [formValues, setFormValues] = useState<Record<string, string>>({});
  // Plaintext fetched on demand via the audit-logged /reveal endpoint.
  // Never populated by the list endpoint, which returns metadata only.
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [revealing, setRevealing] = useState<Record<string, boolean>>({});

  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; details?: any } | null>(null);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' });

  const providerCredentials = credentialsQuery.data?.filter(
    (c) => c.provider === providerName && (!visibleCredentials || visibleCredentials.includes(c.credential_name))
  ) || [];

  // Precedence: unsaved edit > revealed plaintext > mask (configured) > empty (not set).
  const getFieldValue = (cred: CredentialMetadata) => {
    const editedValue = formValues[cred.credential_name];
    if (editedValue !== undefined) return editedValue;
    const revealedValue = revealed[cred.credential_name];
    if (revealedValue !== undefined) return revealedValue;
    return cred.set ? MASK : '';
  };

  // The mask is a placeholder, not a real value — typing must replace it, not append.
  const isMasked = (cred: CredentialMetadata) =>
    formValues[cred.credential_name] === undefined &&
    revealed[cred.credential_name] === undefined &&
    cred.set;

  const handleInputChange = (name: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleFocus = (cred: CredentialMetadata) => {
    if (isMasked(cred)) {
      setFormValues((prev) => ({ ...prev, [cred.credential_name]: '' }));
    }
  };

  // Drop an empty edit on blur so the field falls back to the mask instead of
  // looking like an unconfigured credential.
  const handleBlur = (cred: CredentialMetadata) => {
    if (formValues[cred.credential_name] === '') {
      setFormValues((prev) => {
        const next = { ...prev };
        delete next[cred.credential_name];
        return next;
      });
    }
  };

  const handleToggleVisibility = async (cred: CredentialMetadata) => {
    const name = cred.credential_name;

    // Already showing plaintext — hide it and drop the cache so the next
    // reveal produces a fresh audit-log entry.
    if (revealed[name] !== undefined) {
      setRevealed((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
      return;
    }

    if (revealing[name]) return;

    setRevealing((prev) => ({ ...prev, [name]: true }));
    try {
      const res = await fetcher<CredentialReveal>(
        `/api/admin/credentials/${cred.provider}/${name}/reveal`
      );
      if (res.value === null) {
        setSnackbar({ open: true, message: `${name} is not configured`, severity: 'error' });
        return;
      }
      setRevealed((prev) => ({ ...prev, [name]: res.value as string }));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSnackbar({ open: true, message: `Failed to reveal ${name}: ${message}`, severity: 'error' });
    } finally {
      setRevealing((prev) => ({ ...prev, [name]: false }));
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setTestResult(null);

    const payload = Object.fromEntries(
      Object.entries(formValues).filter(([_, v]) => v.trim() !== '')
    );

    if (Object.keys(payload).length === 0) {
      setSnackbar({ open: true, message: 'No credential values to save', severity: 'error' });
      setIsSaving(false);
      return;
    }

    try {
      await fetcher(`/api/admin/credentials/${providerName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setFormValues({});
      setRevealed({});
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      setSnackbar({ open: true, message: 'Credentials saved', severity: 'success' });
    } catch (err: any) {
      setSnackbar({ open: true, message: `Failed to save credentials: ${err.message}`, severity: 'error' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await fetcher(`/api/admin/test-connection/${providerName}`, {
        method: 'POST',
      });
      setTestResult(res as any);
    } catch (err: any) {
      setTestResult({ success: false, message: err.message });
    } finally {
      setIsTesting(false);
    }
  };

  if (credentialsQuery.isLoading) return <CircularProgress size={24} />;

  if (providerCredentials.length === 0) {
    return <Typography color="text.secondary">No credentials configured for this provider.</Typography>;
  }

  return (
    <Box>
      <Box component="form" onSubmit={handleSave}>
        <Grid container spacing={2}>
          {providerCredentials.map((cred) => (
            <Grid size={{ xs: 12 }} key={cred.credential_name}>
              <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2 }}>
                <TextField
                  fullWidth
                  label={cred.credential_name}
                  type={revealed[cred.credential_name] !== undefined ? 'text' : 'password'}
                  value={getFieldValue(cred)}
                  onChange={(e) => handleInputChange(cred.credential_name, e.target.value)}
                  onFocus={() => handleFocus(cred)}
                  onBlur={() => handleBlur(cred)}
                  size="small"
                  autoComplete="new-password"
                  placeholder={cred.set ? 'Configured' : 'Not set'}
                  slotProps={{
                    input: {
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            onClick={() => handleToggleVisibility(cred)}
                            edge="end"
                            size="small"
                            disabled={!cred.set || revealing[cred.credential_name]}
                            aria-label={
                              revealed[cred.credential_name] !== undefined
                                ? `Hide ${cred.credential_name}`
                                : `Reveal ${cred.credential_name}`
                            }
                          >
                            {revealing[cred.credential_name] ? (
                              <CircularProgress size={18} />
                            ) : revealed[cred.credential_name] !== undefined ? (
                              <VisibilityOff />
                            ) : (
                              <Visibility />
                            )}
                          </IconButton>
                        </InputAdornment>
                      ),
                    },
                  }}
                />
                <Box sx={{ pt: 1, minWidth: 100 }}>
                    <Chip
                      label={cred.set ? 'Configured' : 'Not set'}
                      color={cred.set ? 'success' : 'default'}
                      size="small"
                      variant={cred.set ? 'filled' : 'outlined'}
                  />
                </Box>
              </Box>
            </Grid>
          ))}
          
          <Grid size={{ xs: 12 }} sx={{ display: 'flex', gap: 2, mt: 1 }}>
            <Button
              type="submit"
              variant="contained"
              disabled={isSaving || Object.values(formValues).every((v) => v.trim() === '')}
            >
              {isSaving ? 'Saving...' : 'Save Credentials'}
            </Button>
            <Button
              variant="outlined"
              onClick={handleTestConnection}
              disabled={isTesting}
            >
              {isTesting ? 'Testing...' : 'Test Connection'}
            </Button>
          </Grid>
        </Grid>
      </Box>

      {testResult && (
        <Alert 
          severity={testResult.success ? 'success' : 'error'} 
          sx={{ mt: 3 }}
        >
          {testResult.message}
          {testResult.details && (
            <Box component="details" sx={{ mt: 1 }}>
              <Box component="summary" sx={{ cursor: 'pointer' }}>Details</Box>
              <Box component="pre" sx={{ mt: 1, p: 1, bgcolor: 'background.paper', borderRadius: 1, fontSize: '0.8rem', overflow: 'auto' }}>
                {JSON.stringify(testResult.details, null, 2)}
              </Box>
            </Box>
          )}
        </Alert>
      )}

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
      >
        <Alert onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))} severity={snackbar.severity}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
