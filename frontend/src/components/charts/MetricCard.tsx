'use client'

import type { ReactNode } from 'react'
import type { AnalyticsTone } from '@/lib/analytics'

interface MetricCardProps {
  title: string
  value: string
  detail?: string
  tone?: AnalyticsTone
  icon?: ReactNode
  testId?: string
}

const TONE_CLASSES: Record<AnalyticsTone, string> = {
  emerald: 'border-emerald-400/30 bg-emerald-400/10',
  amber: 'border-amber-400/30 bg-amber-400/10',
  rose: 'border-rose-400/30 bg-rose-400/10',
  slate: 'border-white/10 bg-white/5',
  violet: 'border-violet-400/30 bg-violet-400/10',
}

const VALUE_CLASSES: Record<AnalyticsTone, string> = {
  emerald: 'text-emerald-100',
  amber: 'text-amber-100',
  rose: 'text-rose-100',
  slate: 'text-white',
  violet: 'text-violet-100',
}

export default function MetricCard({
  title,
  value,
  detail,
  tone = 'slate',
  icon,
  testId,
}: MetricCardProps) {
  return (
    <div
      data-testid={testId ?? 'metric-card'}
      className={`rounded-3xl border p-5 ${TONE_CLASSES[tone]}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
          {title}
        </p>
        {icon && (
          <span className="shrink-0 text-slate-400">{icon}</span>
        )}
      </div>
      <p className={`mt-3 text-3xl font-semibold ${VALUE_CLASSES[tone]}`}>
        {value}
      </p>
      {detail && (
        <p className="mt-2 text-sm leading-6 text-slate-400">{detail}</p>
      )}
    </div>
  )
}
