import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import { Providers } from '@/components/providers'
import { SiteHeader } from '@/components/auth/SiteHeader'
import './globals.css'

export const metadata: Metadata = {
  title: 'Live Session Analysis | Nerdy',
  description: 'AI-Powered Real-Time Engagement Analysis for Video Tutoring — A Varsity Tutors Platform',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#1a1f3a] text-slate-100">
        <Providers>
          <SiteHeader />
          {children}
          <Toaster position="bottom-right" richColors />
        </Providers>
      </body>
    </html>
  )
}
