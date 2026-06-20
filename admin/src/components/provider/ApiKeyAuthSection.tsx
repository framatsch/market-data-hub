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

interface CredentialMeta {
  provider: string;
  credential_name: string;
  set: boolean;
  masked_value: string | null;
  updated_at: string | null;
}

export function ApiKeyAuthSection({
  providerName,
  visibleCredentials,
}: {
  providerName: string;
  visibleCredentials?: string[];
}) {
  const queryClient = useQueryClient();
  const credentialsQuery = useQuery<CredentialMeta[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
  });

  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [revealingCredentials, setRevealingCredentials] = useState<Record<string, boolean>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; details?: any } | null>(null);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' });

  const providerCredentials = credentialsQuery.data?.filter(
    (c) => c.provider === providerName && (!visibleCredentials || visibleCredentials.includes(c.credential_name))
  ) || [];

  const getFieldValue = (cred: CredentialMeta) => {
    const editedValue = formValues[cred.credential_name];
    if (editedValue !== undefined) return editedValue;
    return cred.set ? cred.masked_value || '' : '';
  };

  const isShowingMaskedValue = (cred: CredentialMeta) => (
    cred.set && formValues[cred.credential_name] === undefined && !showPasswords[cred.credential_name]
  );

  const handleInputChange = (name: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleInputFocus = (cred: CredentialMeta) => {
    if (!isShowingMaskedValue(cred)) return;
    setFormValues((prev) => ({ ...prev, [cred.credential_name]: '' }));
  };

  const handleToggleVisibility = async (cred: CredentialMeta) => {
    const isVisible = showPasswords[cred.credential_name];
    if (isVisible) {
      setShowPasswords((prev) => ({ ...prev, [cred.credential_name]: false }));
      return;
    }

    // Fetch the stored value whenever the field is either empty OR contains
    // only locally-typed (unsaved) text — i.e. there is a saved credential but
    // the user hasn't explicitly loaded it yet.  We track this with a separate
    // flag so that typing in the field doesn't prevent revealing the real value.
    const alreadyRevealed = revealingCredentials[cred.credential_name + '_loaded'];
    if (cred.set && !alreadyRevealed) {
      setRevealingCredentials((prev) => ({ ...prev, [cred.credential_name]: true }));
      try {
        const res = await fetcher(`/api/admin/credentials/${providerName}/${cred.credential_name}`) as { value: string };
        setFormValues((prev) => ({ ...prev, [cred.credential_name]: res.value }));
        setRevealingCredentials((prev) => ({ ...prev, [cred.credential_name + '_loaded']: true }));
      } catch (err: any) {
        setSnackbar({ open: true, message: `Failed to reveal credential: ${err.message}`, severity: 'error' });
        return;
      } finally {
        setRevealingCredentials((prev) => ({ ...prev, [cred.credential_name]: false }));
      }
    }

    setShowPasswords((prev) => ({ ...prev, [cred.credential_name]: true }));
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
      // Reset visibility and loaded-flags so fields go back to masked placeholder
      // and the next reveal fetches the freshly saved value from the server.
      setShowPasswords({});
      setRevealingCredentials({});
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
                  type={isShowingMaskedValue(cred) || showPasswords[cred.credential_name] ? 'text' : 'password'}
                  value={getFieldValue(cred)}
                  onChange={(e) => handleInputChange(cred.credential_name, e.target.value)}
                  onFocus={() => handleInputFocus(cred)}
                  size="small"
                  placeholder={cred.set ? cred.masked_value || 'Configured' : 'Not set'}
                  slotProps={{
                    input: {
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            onClick={() => handleToggleVisibility(cred)}
                            disabled={revealingCredentials[cred.credential_name]}
                            edge="end"
                            size="small"
                          >
                            {showPasswords[cred.credential_name] ? <VisibilityOff /> : <Visibility />}
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
