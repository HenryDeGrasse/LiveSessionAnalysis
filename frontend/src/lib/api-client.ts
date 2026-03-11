/**
 * Authenticated API client.
 *
 * `apiFetch` is a thin wrapper around the global `fetch` that:
 *   - Prepends `API_URL` so callers only need to pass the path.
 *   - Injects an `Authorization: Bearer <accessToken>` header when a token
 *     is provided.
 *   - Defaults `Content-Type` to `application/json` (can be overridden).
 *
 * Usage in client components (via useSession):
 * ```ts
 * const { data: session } = useSession()
 * const res = await apiFetch('/api/analytics/sessions', {}, session?.accessToken)
 * ```
 *
 * Usage in server components / route handlers (via auth()):
 * ```ts
 * const session = await auth()
 * const res = await apiFetch('/api/analytics/sessions', {}, session?.accessToken)
 * ```
 */
import { API_URL } from './constants'

/**
 * Fetch options extended with an optional access token.
 * The token is pulled out before being passed to the underlying `fetch`.
 */
export interface ApiFetchOptions extends RequestInit {
  /** Backend JWT to send as Authorization: Bearer header. */
  accessToken?: string
}

/**
 * Fetches a backend API endpoint with optional authentication.
 *
 * @param path        - Path relative to API_URL, e.g. '/api/analytics/sessions'.
 * @param options     - Standard RequestInit options plus optional `accessToken`.
 * @returns           - The raw `Response` object.
 */
export async function apiFetch(
  path: string,
  { accessToken, headers: callerHeaders, ...restOptions }: ApiFetchOptions = {}
): Promise<Response> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    // Caller-provided headers override the defaults above.
    ...(callerHeaders as Record<string, string> | undefined),
  }

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`
  }

  return fetch(`${API_URL}${path}`, {
    ...restOptions,
    headers,
  })
}

/**
 * Builds a bound version of `apiFetch` for a known access token.
 * Useful when the token is retrieved once and reused across multiple calls.
 *
 * @param accessToken - Backend JWT or undefined for unauthenticated calls.
 * @returns A function with the same signature as `apiFetch` minus `accessToken`.
 */
export function createAuthenticatedFetch(
  accessToken: string | undefined
): (path: string, options?: Omit<ApiFetchOptions, 'accessToken'>) => Promise<Response> {
  return (path, options = {}) => apiFetch(path, { ...options, accessToken })
}
