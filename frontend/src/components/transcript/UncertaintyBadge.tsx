'use client'

interface UncertaintyBadgeProps {
  /** Topic the student is uncertain about. */
  topic?: string
  /** Uncertainty score (0–1). Displayed as a percentage when provided. */
  score?: number
}

/**
 * Inline indicator shown next to transcript utterances where the student
 * expressed uncertainty. Displays a 🔶 icon and an optional topic label.
 *
 * Tutor-only — never rendered in student views.
 */
export function UncertaintyBadge({ topic, score }: UncertaintyBadgeProps) {
  const label = topic || 'uncertain'
  const title =
    score !== undefined
      ? `Uncertainty: ${label} (${Math.round(score * 100)}%)`
      : `Uncertainty: ${label}`

  return (
    <span
      data-testid="uncertainty-badge"
      title={title}
      className="ml-1.5 inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-200"
    >
      <span aria-hidden="true">🔶</span>
      <span className="max-w-[120px] truncate">{label}</span>
    </span>
  )
}
