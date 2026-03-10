'use client'

import type { FlaggedMoment } from '@/lib/types'
import { formatClock } from '@/lib/analytics'

interface FlaggedMomentBadgeProps {
  moment: FlaggedMoment
  sessionDuration: number
}

export default function FlaggedMomentBadge({
  moment,
  sessionDuration,
}: FlaggedMomentBadgeProps) {
  const isBelow = moment.direction === 'below'
  const toneClasses = isBelow
    ? 'border-rose-400/30 bg-rose-400/10 text-rose-100'
    : 'border-amber-400/30 bg-amber-400/10 text-amber-100'
  const directionLabel = isBelow ? '↓ Below threshold' : '↑ Above threshold'
  const timeLabel = formatClock(moment.timestamp)
  const progressPercent =
    sessionDuration > 0
      ? Math.min((moment.timestamp / sessionDuration) * 100, 100)
      : 0

  return (
    <div
      data-testid="flagged-moment-badge"
      className={`rounded-2xl border p-3 ${toneClasses}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-snug">
            {moment.description}
          </p>
          <p className="mt-1 text-xs opacity-80">
            {moment.metric_name.replace(/_/g, ' ')} · {directionLabel}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-current/20 px-2.5 py-1 text-xs font-medium tabular-nums">
          {timeLabel}
        </span>
      </div>

      {sessionDuration > 0 && (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-white/10">
          <div
            className={`h-full rounded-full ${
              isBelow ? 'bg-rose-400/60' : 'bg-amber-400/60'
            }`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      )}
    </div>
  )
}
