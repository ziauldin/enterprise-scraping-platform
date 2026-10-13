import type { Metadata } from 'next'
import { DM_Sans, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import ScheduledRunsHeartbeat from '@/components/ScheduledRunsHeartbeat'
import Sidebar from '@/components/Sidebar'
import { MotionProvider } from '@/components/providers/MotionProvider'
import { AOSProvider } from '@/components/providers/AOSProvider'
import { PageTransition } from '@/components/providers/PageTransition'
import { ThemeProvider } from '@/components/providers/ThemeProvider'

const uiFont = DM_Sans({
  subsets: ['latin'],
  variable: '--font-ui',
  display: 'swap',
})

const monoFont = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'ParseHub Dashboard',
  description: 'Manual ParseHub project operations with SQLite-backed storage',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${uiFont.variable} ${monoFont.variable} antialiased`}>
        <ThemeProvider>
          <MotionProvider>
            <AOSProvider>
              <ScheduledRunsHeartbeat />
              <div className="flex min-h-screen">
                <Sidebar />
                <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
                  <PageTransition>
                    {children}
                  </PageTransition>
                </div>
              </div>
            </AOSProvider>
          </MotionProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
