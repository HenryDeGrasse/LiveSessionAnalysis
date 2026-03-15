'use client'

interface PartialTranscriptProps {
  /** Speaker label to display, e.g. "Tutor" or "Student". */
  speaker: string
  /** Current partial text being transcribed. */
  text: string
}

/**
 * Live "typing…" indicator for a partial (in-progress) transcript utterance.
 * Updates in-place as new partial revisions arrive, identified by utterance_id
 * in the parent component.
 */
export function PartialTranscript({ speaker, text }: PartialTranscriptProps) {
  return (
    <div
      data-testid="partial-transcript"
      className="flex items-start gap-2 px-3 py-1.5 text-sm text-slate-400 italic"
    >
      <span className="shrink-0 font-medium text-slate-500">{speaker}:</span>
      <span className="min-w-0 break-words">
        {text}
        <span className="ml-1 inline-block animate-pulse">…</span>
      </span>
    </div>
  )
}
