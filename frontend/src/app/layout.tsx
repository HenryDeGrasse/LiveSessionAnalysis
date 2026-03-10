import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import './globals.css'

export const metadata: Metadata = {
  title: 'Live Session Analysis',
  description: 'AI-Powered Real-Time Engagement Analysis for Video Tutoring',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-950 text-slate-100">
        {children}
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  )
}
