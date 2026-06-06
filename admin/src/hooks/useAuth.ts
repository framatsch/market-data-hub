import { useQuery } from '@tanstack/react-query';
import { fetcher } from '../lib/api';

export interface AuthInfo {
  user: string;
  auth_enabled: boolean;
}

export function useAuth() {
  const { data, isLoading, isError, error } = useQuery<AuthInfo>({
    queryKey: ['auth', 'me'],
    queryFn: () => fetcher('/api/admin/auth/me'),
    retry: false, // Don't retry auth check on failure
    staleTime: 60000, // Cache for 1 minute
  });

  return {
    user: data?.user,
    authEnabled: data?.auth_enabled ?? true,
    isLoading,
    isError,
    error,
  };
}
