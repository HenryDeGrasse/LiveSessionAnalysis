'use client'

interface SuggestButtonProps {
  loading: boolean
  onClick: () => void
  callsRemaining?: number | null
  disabled?: boolean
}

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
        'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors',
        isDisabled
          ? 'cursor-not-allowed border-white/5 bg-slate-900/50 text-slate-600'
          : 'border-violet-400/30 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 hover:text-white',
      ].join(' ')}
      aria-label="Get AI suggestion"
    >
      {loading ? (
        <span
          data-testid="suggest-button-spinner"
          className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-400/30 border-t-violet-400"
          aria-hidden="true"
        />
      ) : (
        <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1a2.5 2.5 0 0 0-2.5 2.5c0 .86.43 1.62 1.1 2.07A4.5 4.5 0 0 0 3.5 10v1a.5.5 0 0 0 .5.5h2v2a.5.5 0 0 0 .5.5h3a.5.5 0 0 0 .5-.5v-2h2a.5.5 0 0 0 .5-.5v-1a4.5 4.5 0 0 0-3.1-4.43A2.5 2.5 0 0 0 10.5 3.5 2.5 2.5 0 0 0 8 1z"/>
        </svg>
      )}
      <span>{loading ? 'Thinking...' : 'AI Suggest'}</span>
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
