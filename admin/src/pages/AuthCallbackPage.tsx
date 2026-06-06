import { useEffect, useState, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Box, CircularProgress, Typography, Button, Alert } from '@mui/material';
import { fetcher } from '../lib/api';
import { generateCodeVerifier, generateCodeChallenge } from '../lib/pkce';

export default function AuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const processedRef = useRef(false);

  useEffect(() => {
    async function exchangeToken() {
      if (processedRef.current) return;
      
      const code = searchParams.get('code');
      const verifier = sessionStorage.getItem('pkce_verifier');

      if (!code) {
        setError('No authorization code found in URL.');
        return;
      }

      if (!verifier) {
        setError('No PKCE verifier found. Your session may have expired.');
        return;
      }

      processedRef.current = true;

      try {
        const { access_token } = await fetcher<{ access_token: string }>(
          '/api/admin/auth/token',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, code_verifier: verifier }),
          }
        );

        sessionStorage.setItem('admin_token', access_token);
        sessionStorage.removeItem('pkce_verifier');
        navigate('/admin', { replace: true });
      } catch (e: any) {
        console.error('Token exchange failed:', e);
        setError(e.message || 'Failed to exchange authorization code for token.');
        processedRef.current = false;
      }
    }

    exchangeToken();
  }, [searchParams, navigate]);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const verifier = generateCodeVerifier();
      const challenge = await generateCodeChallenge(verifier);
      
      sessionStorage.setItem('pkce_verifier', verifier);
      
      const { auth_url } = await fetcher<{ auth_url: string }>(
        `/api/admin/auth/url?code_challenge=${challenge}`
      );
      
      window.location.href = auth_url;
    } catch (e: any) {
      setError(`Retry failed: ${e.message}`);
      setRetrying(false);
    }
  };

  if (error) {
    return (
      <Box sx={{ p: 4, maxWidth: 600, mx: 'auto', mt: 8 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
        <Button variant="contained" onClick={handleRetry} disabled={retrying}>
          {retrying ? 'Redirecting...' : 'Try Again'}
        </Button>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
      }}
    >
      <CircularProgress />
      <Typography sx={{ mt: 2 }}>Completing login...</Typography>
    </Box>
  );
}
