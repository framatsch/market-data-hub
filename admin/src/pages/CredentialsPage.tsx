import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Typography,
  Box,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  TextField,
  Button,
  Grid,
  Snackbar,
  Alert,
  CircularProgress,
  Stack,
  Divider,
  Chip,
  List,
  ListItem,
  ListItemText,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import EditIcon from '@mui/icons-material/Edit';
import { fetcher } from '../lib/api';
import type { CredentialMetadata } from '../types';

export default function CredentialsPage() {
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const credentialsQuery = useQuery<CredentialMetadata[]>({
    queryKey: ['credentials'],
    queryFn: () => fetcher('/api/admin/credentials'),
  });

  // Group credentials by provider
  const groupedCredentials = credentialsQuery.data?.reduce((acc, cred) => {
    if (!acc[cred.provider_name]) {
      acc[cred.provider_name] = [];
    }
    acc[cred.provider_name].push(cred);
    return acc;
  }, {} as Record<string, CredentialMetadata[]>) || {};

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        API Credentials
      </Typography>
      <Typography variant="body1" sx={{ mb: 3 }}>
        Manage API keys and secrets. Secrets are stored encrypted and can never be retrieved in plaintext.
      </Typography>

      <Stack spacing={2}>
        {credentialsQuery.isLoading ? (
          <CircularProgress />
        ) : (
          Object.entries(groupedCredentials).map(([provider, creds]) => (
            <CredentialSection
              key={provider}
              provider={provider}
              creds={creds}
              onSuccess={(msg) => setSnackbar({ open: true, message: msg, severity: 'success' })}
              onError={(msg) => setSnackbar({ open: true, message: msg, severity: 'error' })}
            />
          ))
        )}
      </Stack>

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

function CredentialSection({
  provider,
  creds,
  onSuccess,
  onError,
}: {
  provider: string;
  creds: CredentialMetadata[];
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const queryClient = useQueryClient();

  const handleToggleEdit = () => {
    setIsEditing(!isEditing);
    setFormValues({});
  };

  const handleInputChange = (credName: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [credName]: value }));
  };

  const handleSave = async () => {
    // Only send non-empty values
    const payload = Object.fromEntries(
      Object.entries(formValues).filter(([_, v]) => v.trim() !== '')
    );

    if (Object.keys(payload).length === 0) {
      setIsEditing(false);
      return;
    }

    setIsSaving(true);
    try {
      await fetcher(`/api/admin/credentials/${provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      onSuccess(`Credentials updated for ${provider.toUpperCase()}`);
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      setIsEditing(false);
      setFormValues({});
    } catch (err: any) {
      onError(`Failed to save credentials: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Accordion>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', pr: 2 }}>
          <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>{provider.toUpperCase()}</Typography>
          <Stack direction="row" spacing={1}>
            {creds.map((cred) => (
              <Chip
                key={cred.credential_name}
                label={cred.credential_name}
                size="small"
                color={cred.set ? 'success' : 'default'}
                variant={cred.set ? 'filled' : 'outlined'}
              />
            ))}
          </Stack>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Divider sx={{ mb: 2 }} />
        {isEditing ? (
          <Box component="form" sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
              Enter new values for the fields you want to update. Leave blank to keep existing values.
            </Typography>
            <Grid container spacing={2}>
              {creds.map((cred) => (
                <Grid size={12} key={cred.credential_name}>
                  <TextField
                    fullWidth
                    label={cred.credential_name}
                    type="password"
                    size="small"
                    autoComplete="new-password"
                    value={formValues[cred.credential_name] || ''}
                    onChange={(e) => handleInputChange(cred.credential_name, e.target.value)}
                    placeholder={cred.set ? '••••••••' : 'Not configured'}
                  />
                </Grid>
              ))}
              <Grid size={12} sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mt: 1 }}>
                <Button onClick={handleToggleEdit} size="small">
                  Cancel
                </Button>
                <Button
                  variant="contained"
                  onClick={handleSave}
                  size="small"
                  disabled={isSaving}
                >
                  {isSaving ? 'Saving...' : 'Save Changes'}
                </Button>
              </Grid>
            </Grid>
          </Box>
        ) : (
          <Box>
            <List dense>
              {creds.map((cred) => (
                <ListItem key={cred.credential_name} divider>
                  <ListItemText
                    primary={cred.credential_name}
                    secondary={cred.set ? `Last updated: ${cred.updated_at || 'unknown'}` : 'Not configured'}
                  />
                  <Chip
                    label={cred.set ? 'Configured' : 'Missing'}
                    size="small"
                    color={cred.set ? 'success' : 'error'}
                    variant="outlined"
                  />
                </ListItem>
              ))}
            </List>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
              <Button
                variant="outlined"
                startIcon={<EditIcon />}
                onClick={handleToggleEdit}
                size="small"
              >
                Update Credentials
              </Button>
            </Box>
          </Box>
        )}
      </AccordionDetails>
    </Accordion>
  );
}
