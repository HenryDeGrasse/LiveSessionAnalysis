'use client'

interface SuggestButtonProps {
  /** Whether a suggestion request is currently in flight. */
  loading: boolean
  /** Called when the button is clicked. */
  onClick: () => void
  /** Remaining API calls in the budget window. Shown as a badge when non-null. */
  callsRemaining?: number | null
  /** Whether the button should be disabled (e.g. budget exhausted). */
  disabled?: boolean
}

/**
 * Persistent button in the tutor control bar that requests an AI coaching
 * suggestion on demand. Shows a loading spinner when a request is in flight
 * and an optional budget-remaining badge.
 */
export function SuggestButton({
  loading,
  onClick,
  callsRemaining,
  disabled = false,
}: SuggestButtonProps) {
  const isDisabled = disabled || loading

  return (
    <button
      type="button"
      data-testid="suggest-button"
      onClick={onClick}
      disabled={isDisabled}
      className={[
        'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors',
        isDisabled
          ? 'cursor-not-allowed border-white/5 bg-slate-900/50 text-slate-600'
          : 'border-violet-400/30 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 hover:text-white',
      ].join(' ')}
      aria-label="Get AI suggestion"
    >
      {loading ? (
        <span
          data-testid="suggest-button-spinner"
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-violet-400/30 border-t-violet-400"
          aria-hidden="true"
        />
      ) : (
        <span aria-hidden="true">🤖</span>
      )}
      <span>{loading ? 'Thinking…' : 'Get AI Suggestion'}</span>
      {callsRemaining !== null && callsRemaining !== undefined && (
        <span
          data-testid="calls-remaining-badge"
          className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-400"
        >
          {callsRemaining}
        </span>
      )}
    </button>
  )
}
