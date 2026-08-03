import { ReactNode } from 'react'
import Sidebar from './Sidebar'

interface AppLayoutProps {
  children: ReactNode
}

export default function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 bg-[#fafbfc]">
        {children}
      </main>
    </div>
  )
}
