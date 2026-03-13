import { fireEvent, render, screen } from '@testing-library/react'
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

function TestHarness() {
  const {
    nudges,
    nudgeHistory,
    nudgeSoundEnabled,
    handleNudge,
    toggleNudgeSound,
  } = useNudges()

  return (
    <div>
      <div data-testid="sound-state">{nudgeSoundEnabled ? 'on' : 'off'}</div>
      <div data-testid="visible-nudges">{nudges.length}</div>
      <div data-testid="history-count">{nudgeHistory.length}</div>
      <button type="button" onClick={() => handleNudge(SAMPLE_NUDGE)}>
        push nudge
      </button>
      <button type="button" onClick={toggleNudgeSound}>
        toggle sound
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
})
