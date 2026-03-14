'use client'

import type { TranscriptMessage as TranscriptMessageData } from '@/lib/types'
import { UncertaintyBadge } from './UncertaintyBadge'
import { PartialTranscript } from './PartialTranscript'

interface TranscriptMessageProps {
  message: TranscriptMessageData
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const speakerLabel: Record<string, string> = {
  tutor: 'Tutor',
  student: 'Student',
}

const speakerClasses: Record<string, string> = {
  tutor: 'text-sky-300',
  student: 'text-emerald-300',
}

/**
 * Renders a single transcript utterance with speaker label, timestamp, text,
 * and an optional UncertaintyBadge when uncertainty_score is present.
 *
 * Partial messages delegate to PartialTranscript for the live "typing…" display.
 */
export function TranscriptMessage({ message }: TranscriptMessageProps) {
  const label = speakerLabel[message.role] ?? message.role
  const labelClass = speakerClasses[message.role] ?? 'text-slate-300'

  if (message.is_partial) {
    return <PartialTranscript speaker={label} text={message.text} />
  }

  const showUncertainty =
    message.uncertainty_score !== undefined && message.uncertainty_score > 0

  return (
    <div data-testid="transcript-message" className="flex items-start gap-2 px-3 py-1.5 text-sm">
      <span className="shrink-0 w-12 text-[11px] tabular-nums text-slate-500">
        {formatTimestamp(message.start_time)}
      </span>
      <span className={`shrink-0 font-medium ${labelClass}`}>{label}:</span>
      <span className="min-w-0 break-words text-slate-200">
        {message.text}
        {showUncertainty && (
          <UncertaintyBadge
            topic={message.uncertainty_topic}
            score={message.uncertainty_score}
          />
        )}
      </span>
    </div>
  )
}
