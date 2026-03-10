'use client'

export interface DonutSegment {
  label: string
  value: number
  color: string
}

interface DonutChartProps {
  segments: DonutSegment[]
  size?: number
  innerLabel?: string
  innerSublabel?: string
}

const STROKE_WIDTH = 28
const GAP_DEGREES = 2

export default function DonutChart({
  segments,
  size = 180,
  innerLabel,
  innerSublabel,
}: DonutChartProps) {
  const radius = (size - STROKE_WIDTH) / 2
  const circumference = 2 * Math.PI * radius
  const center = size / 2

  const total = segments.reduce((sum, segment) => sum + segment.value, 0)

  if (total === 0) {
    return (
      <div
        data-testid="donut-chart"
        className="flex items-center justify-center"
        style={{ width: size, height: size }}
      >
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="rgba(148,163,184,0.15)"
            strokeWidth={STROKE_WIDTH}
          />
          {innerLabel && (
            <text
              x={center}
              y={innerSublabel ? center - 6 : center}
              textAnchor="middle"
              dominantBaseline="central"
              className="fill-white text-lg font-semibold"
            >
              {innerLabel}
            </text>
          )}
          {innerSublabel && (
            <text
              x={center}
              y={center + 14}
              textAnchor="middle"
              dominantBaseline="central"
              className="fill-slate-400 text-xs"
            >
              {innerSublabel}
            </text>
          )}
        </svg>
      </div>
    )
  }

  const visibleSegments = segments.filter((segment) => segment.value > 0)
  const totalGapDegrees = visibleSegments.length * GAP_DEGREES
  const availableDegrees = 360 - totalGapDegrees

  let cumulativeOffset = 0
  const arcs = visibleSegments.map((segment) => {
    const segmentDegrees = (segment.value / total) * availableDegrees
    const dashLength = (segmentDegrees / 360) * circumference
    const dashOffset = -((cumulativeOffset / 360) * circumference)

    cumulativeOffset += segmentDegrees + GAP_DEGREES

    return {
      ...segment,
      dashArray: `${dashLength} ${circumference - dashLength}`,
      dashOffset,
    }
  })

  return (
    <div
      data-testid="donut-chart"
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: 'rotate(-90deg)' }}
      >
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="rgba(148,163,184,0.08)"
          strokeWidth={STROKE_WIDTH}
        />
        {arcs.map((arc) => (
          <circle
            key={arc.label}
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={arc.color}
            strokeWidth={STROKE_WIDTH}
            strokeDasharray={arc.dashArray}
            strokeDashoffset={arc.dashOffset}
            strokeLinecap="round"
          />
        ))}
      </svg>

      {(innerLabel || innerSublabel) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {innerLabel && (
            <span className="text-lg font-semibold text-white">
              {innerLabel}
            </span>
          )}
          {innerSublabel && (
            <span className="mt-0.5 text-xs text-slate-400">
              {innerSublabel}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
