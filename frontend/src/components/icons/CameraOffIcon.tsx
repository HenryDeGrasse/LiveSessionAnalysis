import type { SVGProps } from 'react'

export default function CameraOffIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ?? 'h-6 w-6'}
      aria-hidden="true"
      {...props}
    >
      <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" />
      <path d="M7.5 4H14a2 2 0 0 1 2 2v2" />
      <path d="M23 7 16 12 23 17z" />
      <line x1="2" y1="2" x2="22" y2="22" />
    </svg>
  )
}
