import React, { useEffect, useState } from 'react';
import { Box, CircularProgress, Typography } from '@mui/material';
import { useAuth } from '../hooks/useAuth';
import { generateCodeVerifier, generateCodeChallenge } from '../lib/pkce';
import { fetcher } from '../lib/api';

interface AuthGuardProps {
  children: React.ReactNode;
}

export default function AuthGuard({ children }: AuthGuardProps) {
  const { authEnabled, user, isLoading, isError, error } = useAuth();
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    async function initiateAuth() {
      if (!isLoading && isError && (error as any)?.message?.includes('401') || (!isLoading && !user && authEnabled)) {
        setRedirecting(true);
        try {
          const verifier = generateCodeVerifier();
          const challenge = await generateCodeChallenge(verifier);
          
          sessionStorage.setItem('pkce_verifier', verifier);
          
          const { auth_url } = await fetcher<{ auth_url: string }>(
            `/api/admin/auth/url?code_challenge=${challenge}`
          );
          
          window.location.href = auth_url;
        } catch (e) {
          console.error('Failed to initiate auth:', e);
          setRedirecting(false);
        }
      }
    }

    if (authEnabled) {
      initiateAuth();
    }
  }, [isLoading, isError, error, user, authEnabled]);

  if (isLoading || redirecting) {
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
        <Typography sx={{ mt: 2 }}>
          {redirecting ? 'Redirecting to login...' : 'Checking authentication...'}
        </Typography>
      </Box>
    );
  }

  // If auth is disabled or we have a user, show children
  if (!authEnabled || user) {
    return <>{children}</>;
  }

  // If we got here but aren't loading/redirecting, something is wrong
  return (
    <Box sx={{ p: 4, textAlign: 'center' }}>
      <Typography color="error">
        Authentication failed. Please refresh or contact an administrator.
      </Typography>
    </Box>
  );
}
