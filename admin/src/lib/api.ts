/**
 * Base API fetcher with Authorization header support
 */

export async function fetcher<T>(url: string, options: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem('admin_token');
  
  const headers = new Headers(options.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  
  const response = await fetch(url, { ...options, headers });
  
  if (response.status === 401) {
    // AuthGuard will handle redirection if it's a 401 on initial load
    // For other cases, we might want to clear the token
    if (token) {
      sessionStorage.removeItem('admin_token');
    }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `API request failed with status ${response.status}`);
  }
  
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}
