import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useTranscript } from './useTranscript'
import type { TranscriptMessage, WSMessage } from '@/lib/types'

afterEach(cleanup)

/** Helper component that renders hook state for testing. */
function TestHarness({
  bufferLimit,
  onReady,
}: {
  bufferLimit?: number
  onReady: (api: ReturnType<typeof useTranscript>) => void
}) {
  const api = useTranscript({ bufferLimit })
  // Expose the API to the test via callback ref (called every render)
  onReady(api)

  return (
    <div>
      <div data-testid="count">{api.messages.length}</div>
      <div data-testid="texts">
        {api.messages.map((m) => m.text).join('|')}
      </div>
      <div data-testid="ids">
        {api.messages.map((m) => m.utterance_id).join('|')}
      </div>
      <div data-testid="partials">
        {api.messages.map((m) => (m.is_partial ? 'P' : 'F')).join('|')}
      </div>
      <div data-testid="starts">
        {api.messages.map((m) => m.start_time).join('|')}
      </div>
    </div>
  )
}

function makeMsg(overrides: Partial<TranscriptMessage> & { utterance_id: string }): TranscriptMessage {
  return {
    revision: 1,
    role: 'student',
    text: 'hello',
    start_time: 0,
    end_time: 1,
    is_partial: false,
    ...overrides,
  }
}

describe('useTranscript', () => {
  it('adds a partial message and displays it', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    expect(screen.getByTestId('count')).toHaveTextContent('0')

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hel', is_partial: true, revision: 1, start_time: 1 })
      )
    })

    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.getByTestId('texts')).toHaveTextContent('Hel')
    expect(screen.getByTestId('partials')).toHaveTextContent('P')
  })

  it('updates a partial with a newer revision', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hel', is_partial: true, revision: 1, start_time: 1 })
      )
    })

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hello wo', is_partial: true, revision: 2, start_time: 1 })
      )
    })

    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.getByTestId('texts')).toHaveTextContent('Hello wo')
  })

  it('ignores stale partial revisions', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hello wo', is_partial: true, revision: 3, start_time: 1 })
      )
    })

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hel', is_partial: true, revision: 1, start_time: 1 })
      )
    })

    expect(screen.getByTestId('texts')).toHaveTextContent('Hello wo')
  })

  it('replaces a partial with a final message', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hel', is_partial: true, revision: 1, start_time: 1 })
      )
    })

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hello world', is_partial: false, revision: 2, start_time: 1, end_time: 3 })
      )
    })

    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.getByTestId('texts')).toHaveTextContent('Hello world')
    expect(screen.getByTestId('partials')).toHaveTextContent('F')
  })

  it('does not overwrite a final message with a partial', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hello world', is_partial: false, revision: 2, start_time: 1 })
      )
    })

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'Hel', is_partial: true, revision: 3, start_time: 1 })
      )
    })

    expect(screen.getByTestId('texts')).toHaveTextContent('Hello world')
    expect(screen.getByTestId('partials')).toHaveTextContent('F')
  })

  it('handles transcript websocket messages', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    const message: WSMessage = {
      type: 'transcript_partial',
      data: {
        utterance_id: 'u1',
        revision: 2,
        role: 'student',
        text: 'I think...',
        start_time: 12,
        end_time: 12,
        is_partial: true,
      },
    }

    act(() => {
      api.handleTranscriptMessage(message)
    })

    expect(screen.getByTestId('texts')).toHaveTextContent('I think...')
    expect(screen.getByTestId('partials')).toHaveTextContent('P')
    expect(screen.getByTestId('starts')).toHaveTextContent('12')
  })

  it('handles livekit transcript packets and normalizes backend partial payloads', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    const payload = new TextEncoder().encode(JSON.stringify({
      type: 'transcript_partial',
      data: {
        utterance_id: 'u1',
        revision: 3,
        role: 'student',
        text: 'Maybe the derivative?',
        session_time: 8.5,
      },
    }))

    act(() => {
      api.handleTranscriptPacket('lsa.transcript.partial.v1', payload)
    })

    expect(screen.getByTestId('texts')).toHaveTextContent('Maybe the derivative?')
    expect(screen.getByTestId('partials')).toHaveTextContent('P')
    expect(screen.getByTestId('starts')).toHaveTextContent('8.5')
  })

  it('sorts messages by start_time', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u3', text: 'third', start_time: 10 })
      )
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u1', text: 'first', start_time: 1 })
      )
      api.handleTranscriptMessage(
        makeMsg({ utterance_id: 'u2', text: 'second', start_time: 5 })
      )
    })

    expect(screen.getByTestId('texts')).toHaveTextContent('first|second|third')
  })

  it('trims old messages beyond buffer limit', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness bufferLimit={3} onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u1', text: 'a', start_time: 1 }))
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u2', text: 'b', start_time: 2 }))
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u3', text: 'c', start_time: 3 }))
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u4', text: 'd', start_time: 4 }))
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u5', text: 'e', start_time: 5 }))
    })

    expect(screen.getByTestId('count')).toHaveTextContent('3')
    // Oldest entries (u1, u2) should have been trimmed
    expect(screen.getByTestId('texts')).toHaveTextContent('c|d|e')
  })

  it('clears the transcript', () => {
    let api!: ReturnType<typeof useTranscript>

    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleTranscriptMessage(makeMsg({ utterance_id: 'u1', text: 'hello', start_time: 1 }))
    })

    expect(screen.getByTestId('count')).toHaveTextContent('1')

    act(() => {
      api.clearTranscript()
    })

    expect(screen.getByTestId('count')).toHaveTextContent('0')
  })
})
