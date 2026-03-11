import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, createAuthenticatedFetch } from '../api-client'

// ---------------------------------------------------------------------------
// Mock global fetch so we can inspect the calls without network I/O.
// ---------------------------------------------------------------------------
const mockFetch = vi.fn<typeof fetch>()

beforeEach(() => {
  mockFetch.mockClear()
  vi.stubGlobal('fetch', mockFetch)
  mockFetch.mockResolvedValue(new Response('{}', { status: 200 }))
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// apiFetch — header injection
// ---------------------------------------------------------------------------
describe('apiFetch', () => {
  it('prepends API_URL to the path', async () => {
    await apiFetch('/api/analytics/sessions')

    expect(mockFetch).toHaveBeenCalledOnce()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/analytics/sessions')
  })

  it('sets Content-Type to application/json by default', async () => {
    await apiFetch('/api/sessions')

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('does NOT add Authorization header when no accessToken is given', async () => {
    await apiFetch('/api/sessions')

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Authorization']).toBeUndefined()
  })

  it('adds Authorization: Bearer header when accessToken is provided', async () => {
    await apiFetch('/api/sessions', { accessToken: 'my-jwt-token' })

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer my-jwt-token')
  })

  it('caller headers override defaults', async () => {
    await apiFetch('/api/sessions', {
      headers: { 'Content-Type': 'text/plain', 'X-Custom': 'yes' },
    })

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('text/plain')
    expect(headers['X-Custom']).toBe('yes')
  })

  it('passes through additional fetch options (method, body)', async () => {
    await apiFetch('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ tutor_id: 'tutor-1' }),
    })

    const [, init] = mockFetch.mock.calls[0]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe('{"tutor_id":"tutor-1"}')
  })

  it('returns the raw Response', async () => {
    const mockResponse = new Response('{"ok":true}', { status: 201 })
    mockFetch.mockResolvedValue(mockResponse)

    const res = await apiFetch('/api/sessions', { method: 'POST' })
    expect(res.status).toBe(201)
  })
})

// ---------------------------------------------------------------------------
// createAuthenticatedFetch — bound factory
// ---------------------------------------------------------------------------
describe('createAuthenticatedFetch', () => {
  it('returns a function that injects the bound token', async () => {
    const boundFetch = createAuthenticatedFetch('bound-token')
    await boundFetch('/api/analytics/sessions')

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer bound-token')
  })

  it('works without a token (unauthenticated variant)', async () => {
    const boundFetch = createAuthenticatedFetch(undefined)
    await boundFetch('/api/analytics/sessions')

    const [, init] = mockFetch.mock.calls[0]
    const headers = init?.headers as Record<string, string>
    expect(headers['Authorization']).toBeUndefined()
  })

  it('caller options are still respected', async () => {
    const boundFetch = createAuthenticatedFetch('tok')
    await boundFetch('/api/sessions', { method: 'DELETE' })

    const [, init] = mockFetch.mock.calls[0]
    expect(init?.method).toBe('DELETE')
    const headers = init?.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer tok')
  })
})
