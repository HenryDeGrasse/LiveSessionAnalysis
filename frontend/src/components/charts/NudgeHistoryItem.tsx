'use client'

import { formatNudgePriority } from '@/lib/analytics'

interface NudgeHistoryItemProps {
  nudge: {
    nudge_type: string
    message: string
    timestamp: string
    priority: string
  }
}

function formatNudgeTimestamp(isoTimestamp: string): string {
  try {
    const date = new Date(isoTimestamp)
    if (isNaN(date.getTime())) return isoTimestamp
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return isoTimestamp
  }
}

function startCase(value: string): string {
  return value
    .trim()
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const PRIORITY_BADGE: Record<string, string> = {
  emerald: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  amber: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  rose: 'border-rose-400/30 bg-rose-400/10 text-rose-100',
  slate: 'border-white/15 bg-white/5 text-slate-200',
  violet: 'border-violet-400/30 bg-violet-400/10 text-violet-100',
}

export default function NudgeHistoryItem({ nudge }: NudgeHistoryItemProps) {
  const { label: priorityLabel, tone } = formatNudgePriority(nudge.priority)
  const badgeClasses = PRIORITY_BADGE[tone] || PRIORITY_BADGE.slate
  const typeLabel = startCase(nudge.nudge_type)

  return (
    <div
      data-testid="nudge-history-item"
      className="rounded-2xl border border-white/10 bg-slate-950/40 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-white">{typeLabel}</p>
            <span
              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${badgeClasses}`}
            >
              {priorityLabel}
            </span>
          </div>
          <p className="mt-1.5 text-sm leading-6 text-slate-300">
            {nudge.message}
          </p>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-slate-500">
          {formatNudgeTimestamp(nudge.timestamp)}
        </span>
      </div>
    </div>
  )
}
