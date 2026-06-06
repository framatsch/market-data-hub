import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Typography,
  Box,
  TextField,
  Button,
  Grid,
  Snackbar,
  Alert,
  CircularProgress,
  Paper,
  Stepper,
  Step,
  StepLabel,
  StepContent,
  IconButton,
  InputAdornment,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { fetcher } from '../lib/api';
import type { SchwabStatus } from '../types';

export default function SchwabAuthPage() {
  const queryClient = useQueryClient();
  const [activeStep, setActiveStep] = useState(0);
  const [authUrl, setAuthUrl] = useState('');
  const [callbackUrl, setCallbackUrl] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const statusQuery = useQuery<SchwabStatus>({
    queryKey: ['schwab', 'status'],
    queryFn: () => fetcher('/api/admin/schwab/auth/status'),
  });

  const handleGetUrl = async () => {
    setIsProcessing(true);
    try {
      const { auth_url } = await fetcher<{ auth_url: string }>('/api/admin/schwab/auth/url');
      setAuthUrl(auth_url);
      setActiveStep(1);
    } catch (err: any) {
      setSnackbar({ open: true, message: `Failed to get Auth URL: ${err.message}`, severity: 'error' });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleCompleteAuth = async () => {
    setIsProcessing(true);
    try {
      await fetcher('/api/admin/schwab/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: callbackUrl }),
      });
      setSnackbar({ open: true, message: 'Schwab authorization successful!', severity: 'success' });
      queryClient.invalidateQueries({ queryKey: ['schwab', 'status'] });
      setActiveStep(0);
      setAuthUrl('');
      setCallbackUrl('');
    } catch (err: any) {
      setSnackbar({ open: true, message: `Authorization failed: ${err.message}`, severity: 'error' });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(authUrl);
    setSnackbar({ open: true, message: 'URL copied to clipboard', severity: 'success' });
  };

  if (statusQuery.isLoading) return <CircularProgress />;

  const status = statusQuery.data;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Schwab API Authorization
      </Typography>
      <Typography variant="body1" sx={{ mb: 4 }}>
        Schwab API requires manual re-authorization every 7 days. Use this workflow to update your tokens.
      </Typography>

      <Paper variant="outlined" sx={{ p: 3, mb: 4, bgcolor: 'background.default' }}>
        <Typography variant="h6" gutterBottom>Current Status</Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, md: 3 }}>
            <Typography variant="caption" color="text.secondary">Token Status</Typography>
            <Typography variant="body1" sx={{ fontWeight: 600, color: status?.status === 'active' ? 'success.main' : 'error.main' }}>
              {status?.status?.toUpperCase() || 'UNKNOWN'}
            </Typography>
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <Typography variant="caption" color="text.secondary">Paused</Typography>
            <Typography variant="body1">{status?.paused ? 'YES' : 'NO'}</Typography>
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <Typography variant="caption" color="text.secondary">Days Remaining</Typography>
            <Typography variant="body1">{status?.days_remaining ?? 'N/A'}</Typography>
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <Typography variant="caption" color="text.secondary">Expires At</Typography>
            <Typography variant="body1">{status?.expires_at ? new Date(status.expires_at).toLocaleDateString() : 'N/A'}</Typography>
          </Grid>
        </Grid>
      </Paper>

      <Stepper activeStep={activeStep} orientation="vertical">
        <Step>
          <StepLabel>Generate Authorization URL</StepLabel>
          <StepContent>
            <Typography variant="body2" sx={{ mb: 2 }}>
              Generate a unique URL to start the Schwab OAuth2 flow. You will need to log in to your Schwab account.
            </Typography>
            <Button
              variant="contained"
              onClick={handleGetUrl}
              disabled={isProcessing}
            >
              Generate URL
            </Button>
          </StepContent>
        </Step>
        <Step>
          <StepLabel>Authorize and Copy Redirect URL</StepLabel>
          <StepContent>
            <Typography variant="body2" sx={{ mb: 2 }}>
              1. Open the URL below in a new tab.<br />
              2. Log in and authorize the application.<br />
              3. You will be redirected to a blank page or a 404 page.<br />
              4. <strong>Copy the entire URL</strong> from your browser's address bar.
            </Typography>
            <TextField
              fullWidth
              value={authUrl}
              size="small"
              sx={{ mb: 2 }}
              slotProps={{
                input: {
                  readOnly: true,
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton onClick={handleCopyUrl} edge="end" title="Copy to clipboard">
                        <ContentCopyIcon />
                      </IconButton>
                      <IconButton
                        component="a"
                        href={authUrl}
                        target="_blank"
                        edge="end"
                        title="Open in new tab"
                        sx={{ ml: 1 }}
                      >
                        <OpenInNewIcon />
                      </IconButton>
                    </InputAdornment>
                  ),
                }
              }}
            />
            <Box sx={{ mb: 2 }}>
              <Button
                variant="contained"
                onClick={() => setActiveStep(2)}
                sx={{ mt: 1, mr: 1 }}
              >
                I have the redirect URL
              </Button>
              <Button
                onClick={() => setActiveStep(0)}
                sx={{ mt: 1, mr: 1 }}
              >
                Back
              </Button>
            </Box>
          </StepContent>
        </Step>
        <Step>
          <StepLabel>Complete Authorization</StepLabel>
          <StepContent>
            <Typography variant="body2" sx={{ mb: 2 }}>
              Paste the full redirect URL you copied from your browser.
            </Typography>
            <TextField
              fullWidth
              multiline
              rows={3}
              placeholder="https://127.0.0.1/?code=...&session_state=..."
              value={callbackUrl}
              onChange={(e) => setCallbackUrl(e.target.value)}
              sx={{ mb: 2 }}
            />
            <Box sx={{ mb: 2 }}>
              <Button
                variant="contained"
                onClick={handleCompleteAuth}
                disabled={isProcessing || !callbackUrl}
                sx={{ mt: 1, mr: 1 }}
              >
                {isProcessing ? 'Processing...' : 'Complete Authorization'}
              </Button>
              <Button
                onClick={() => setActiveStep(1)}
                sx={{ mt: 1, mr: 1 }}
              >
                Back
              </Button>
            </Box>
          </StepContent>
        </Step>
      </Stepper>

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
