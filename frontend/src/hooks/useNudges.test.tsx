import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNudges } from './useNudges'
import type { Nudge } from '@/lib/types'

const SAMPLE_NUDGE: Nudge = {
  id: 'nudge-1',
  timestamp: '2026-03-13T01:00:00Z',
  nudge_type: 'student_attention',
  message: 'Try re-engaging the student',
  priority: 'medium',
  trigger_metrics: {},
}

const SAMPLE_AI_NUDGE: Nudge = {
  id: 'nudge-ai-1',
  timestamp: '2026-03-13T01:01:00Z',
  nudge_type: 'ai_coaching_suggestion',
  message: 'Try asking the student to explain their reasoning aloud.',
  priority: 'high',
  trigger_metrics: {
    topic: 'fractions',
    observation: 'The student is hesitating before answering.',
    suggested_prompt: 'Can you walk me through how you got that answer?',
    confidence: 0.82,
  },
}

function TestHarness() {
  const {
    nudges,
    nudgeHistory,
    nudgeSoundEnabled,
    aiSuggestionFromNudge,
    handleNudge,
    toggleNudgeSound,
    clearAiSuggestionFromNudge,
  } = useNudges()

  return (
    <div>
      <div data-testid="sound-state">{nudgeSoundEnabled ? 'on' : 'off'}</div>
      <div data-testid="visible-nudges">{nudges.length}</div>
      <div data-testid="history-count">{nudgeHistory.length}</div>
      <div data-testid="ai-suggestion-text">{aiSuggestionFromNudge?.suggestion ?? ''}</div>
      <div data-testid="ai-observation-text">{aiSuggestionFromNudge?.observation ?? ''}</div>
      <div data-testid="ai-topic">{aiSuggestionFromNudge?.topic ?? ''}</div>
      <button type="button" onClick={() => handleNudge(SAMPLE_NUDGE)}>
        push nudge
      </button>
      <button type="button" onClick={() => handleNudge(SAMPLE_AI_NUDGE)}>
        push ai nudge
      </button>
      <button type="button" onClick={toggleNudgeSound}>
        toggle sound
      </button>
      <button type="button" onClick={clearAiSuggestionFromNudge}>
        clear ai suggestion
      </button>
    </div>
  )
}

describe('useNudges', () => {
  const originalAudioContext = window.AudioContext
  const originalWebkitAudioContext = (
    window as Window & { webkitAudioContext?: typeof AudioContext }
  ).webkitAudioContext

  let audioContextCtor: ReturnType<typeof vi.fn>

  beforeEach(() => {
    const oscillator = {
      connect: vi.fn(),
      frequency: { setValueAtTime: vi.fn() },
      start: vi.fn(),
      stop: vi.fn(),
      onended: null as null | (() => void),
      type: 'sine' as OscillatorType,
    }
    const gainNode = {
      connect: vi.fn(),
      gain: {
        setValueAtTime: vi.fn(),
        linearRampToValueAtTime: vi.fn(),
      },
    }

    function MockAudioContext() {
      return {
        currentTime: 0,
        destination: {},
        createOscillator: vi.fn(() => oscillator),
        createGain: vi.fn(() => gainNode),
        close: vi.fn(() => Promise.resolve()),
      }
    }

    audioContextCtor = vi.fn(MockAudioContext)

    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      writable: true,
      value: audioContextCtor,
    })
    Object.defineProperty(window, 'webkitAudioContext', {
      configurable: true,
      writable: true,
      value: undefined,
    })
  })

  afterEach(() => {
    cleanup()
    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      writable: true,
      value: originalAudioContext,
    })
    Object.defineProperty(window, 'webkitAudioContext', {
      configurable: true,
      writable: true,
      value: originalWebkitAudioContext,
    })
    vi.restoreAllMocks()
  })

  it('plays a chime for new nudges by default and can be muted for the session', () => {
    render(<TestHarness />)

    expect(screen.getByTestId('sound-state')).toHaveTextContent('on')

    fireEvent.click(screen.getByText('push nudge'))
    expect(audioContextCtor).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('visible-nudges')).toHaveTextContent('1')
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')

    fireEvent.click(screen.getByText('toggle sound'))
    expect(screen.getByTestId('sound-state')).toHaveTextContent('off')

    fireEvent.click(screen.getByText('push nudge'))
    expect(audioContextCtor).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('visible-nudges')).toHaveTextContent('2')
    expect(screen.getByTestId('history-count')).toHaveTextContent('2')
  })

  it('routes ai coaching nudges into dedicated ai suggestion state', () => {
    render(<TestHarness />)

    fireEvent.click(screen.getByText('push ai nudge'))

    expect(screen.getByTestId('visible-nudges')).toHaveTextContent('0')
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')
    expect(screen.getByTestId('ai-suggestion-text')).toHaveTextContent(
      'Try asking the student to explain their reasoning aloud.'
    )
    expect(screen.getByTestId('ai-observation-text')).toHaveTextContent(
      'The student is hesitating before answering.'
    )
    expect(screen.getByTestId('ai-topic')).toHaveTextContent('fractions')
  })

  it('falls back to the nudge message when ai suggestion text is missing', () => {
    render(<TestHarness />)

    fireEvent.click(screen.getByText('push ai nudge'))

    expect(screen.getByTestId('ai-suggestion-text')).toHaveTextContent(
      SAMPLE_AI_NUDGE.message
    )
  })

  it('can clear ai suggestion state independently from rule nudges', () => {
    render(<TestHarness />)

    fireEvent.click(screen.getByText('push ai nudge'))
    expect(screen.getByTestId('ai-suggestion-text')).toHaveTextContent(
      SAMPLE_AI_NUDGE.message
    )

    fireEvent.click(screen.getByText('clear ai suggestion'))
    expect(screen.getByTestId('ai-suggestion-text')).toHaveTextContent('')
    expect(screen.getByTestId('visible-nudges')).toHaveTextContent('0')
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')
  })
})
