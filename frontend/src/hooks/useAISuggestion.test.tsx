import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAISuggestion } from './useAISuggestion'

// Helper to create a mock JSON response (non-SSE)
function mockJsonResponse(status: number, body: Record<string, unknown>) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    body: null,
  } as unknown as Response
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function TestHarness({
  sessionId,
  accessToken,
  onReady,
}: {
  sessionId: string
  accessToken?: string
  onReady: (api: ReturnType<typeof useAISuggestion>) => void
}) {
  const api = useAISuggestion({ sessionId, accessToken })
  onReady(api)

  return (
    <div>
      <div data-testid="loading">{api.loading ? 'yes' : 'no'}</div>
      <div data-testid="error">{api.error ?? 'null'}</div>
      <div data-testid="suggestion">
        {api.suggestion ? api.suggestion.topic : 'null'}
      </div>
      <div data-testid="calls-remaining">
        {api.callsRemaining !== null ? api.callsRemaining : 'null'}
      </div>
      <div data-testid="history-count">{api.history.length}</div>
      <div data-testid="streaming">{api.streamingText || 'null'}</div>
    </div>
  )
}

describe('useAISuggestion', () => {
  beforeEach(() => {
    vi.spyOn(global, 'fetch')
  })

  it('starts with no suggestion and not loading', () => {
    let api!: ReturnType<typeof useAISuggestion>
    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    expect(screen.getByTestId('loading')).toHaveTextContent('no')
    expect(screen.getByTestId('suggestion')).toHaveTextContent('null')
    expect(screen.getByTestId('error')).toHaveTextContent('null')
    expect(api.history).toHaveLength(0)
  })

  it('fetches a suggestion via JSON fallback and updates state', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(200, {
        status: 'ok',
        calls_remaining: 5,
        suggestion: {
          id: 'ai-sug-1',
          topic: 'fractions',
          observation: 'Student is struggling',
          suggestion: 'Try visuals',
          suggested_prompt: 'Can you draw it?',
          priority: 'medium',
          confidence: 0.85,
        },
      })
    )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('suggestion')).toHaveTextContent('fractions')
    expect(screen.getByTestId('calls-remaining')).toHaveTextContent('5')
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')
    expect(screen.getByTestId('error')).toHaveTextContent('null')
  })

  it('handles no_suggestion response', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(200, { status: 'no_suggestion' })
    )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('suggestion')).toHaveTextContent('null')
    expect(screen.getByTestId('error')).toHaveTextContent(
      'No suggestion available'
    )
  })

  it('handles 429 rate limit', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(429, { detail: 'Budget exceeded' })
    )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('error')).toHaveTextContent('budget exhausted')
  })

  it('handles HTTP error', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(500, { detail: 'Internal error' })
    )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('error')).toHaveTextContent('Internal error')
  })

  it('handles network error', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockRejectedValue(new Error('Failed to fetch'))

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('error')).toHaveTextContent('Failed to fetch')
  })

  it('clears suggestion and error', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(200, {
        status: 'ok',
        calls_remaining: 3,
        suggestion: {
          id: 'ai-sug-2',
          topic: 'algebra',
          observation: 'o',
          suggestion: 's',
          suggested_prompt: 'p',
          priority: 'low',
          confidence: 0.7,
        },
      })
    )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(screen.getByTestId('suggestion')).toHaveTextContent('algebra')

    act(() => {
      api.clearSuggestion()
    })

    expect(screen.getByTestId('suggestion')).toHaveTextContent('null')
    expect(screen.getByTestId('error')).toHaveTextContent('null')
  })

  it('tracks multiple suggestions in history', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    const makeSuggestionResponse = (id: string, topic: string) =>
      mockJsonResponse(200, {
        status: 'ok',
        calls_remaining: 3,
        suggestion: {
          id,
          topic,
          observation: 'o',
          suggestion: 's',
          suggested_prompt: 'p',
          priority: 'medium',
          confidence: 0.8,
        },
      })

    vi.mocked(global.fetch)
      .mockResolvedValueOnce(makeSuggestionResponse('sug-a', 'topic-a'))
      .mockResolvedValueOnce(makeSuggestionResponse('sug-b', 'topic-b'))

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(api.history).toHaveLength(2)
    expect(api.history[0].suggestion.topic).toBe('topic-a')
    expect(api.history[1].suggestion.topic).toBe('topic-b')
  })

  it('sends correct URL with token and auth header', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch).mockResolvedValue(
      mockJsonResponse(200, { status: 'no_suggestion' })
    )

    render(
      <TestHarness
        sessionId="my-session"
        accessToken="my-token"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/sessions/my-session/suggest?token=my-token'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          Authorization: 'Bearer my-token',
        }),
      })
    )
  })

  it('submits feedback', async () => {
    let api!: ReturnType<typeof useAISuggestion>

    vi.mocked(global.fetch)
      .mockResolvedValueOnce(
        mockJsonResponse(200, {
          status: 'ok',
          calls_remaining: 4,
          suggestion: {
            id: 'ai-sug-3',
            topic: 'geometry',
            observation: 'o',
            suggestion: 's',
            suggested_prompt: 'p',
            priority: 'high',
            confidence: 0.95,
          },
        })
      )
      .mockResolvedValueOnce(
        mockJsonResponse(200, { status: 'ok' })
      )

    render(
      <TestHarness
        sessionId="s1"
        accessToken="tok"
        onReady={(a) => { api = a }}
      />
    )

    await act(async () => {
      await api.requestSuggestion()
    })

    expect(api.history).toHaveLength(1)
    expect(api.history[0].feedback).toBeUndefined()

    await act(async () => {
      await api.submitFeedback('ai-sug-3', true)
    })

    expect(api.history).toHaveLength(1)
    expect(api.history[0].feedback).toEqual({ helpful: true })
  })
})
