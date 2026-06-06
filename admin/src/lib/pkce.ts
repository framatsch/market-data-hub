/**
 * PKCE (Proof Key for Code Exchange) helpers using Web Crypto API
 */

export function generateCodeVerifier(): string {
  const array = new Uint32Array(56);
  window.crypto.getRandomValues(array);
  return Array.from(array, (dec) => ('0' + dec.toString(16)).substr(-2)).join('');
}

export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await window.crypto.subtle.digest('SHA-256', data);
  return b64utrim(btoa(String.fromCharCode(...new Uint8Array(digest))));
}

function b64utrim(str: string): string {
  return str.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
