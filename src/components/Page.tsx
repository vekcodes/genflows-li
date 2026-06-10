import type { ReactNode } from 'react'

interface PageProps {
  title: string
  subtitle: string
  moat?: boolean
  kicker?: string
  children: ReactNode
}

export function Page({ title, subtitle, moat, kicker, children }: PageProps) {
  return (
    <div className="page">
      <header className="page-head">
        {kicker && <div className="page-stage">{kicker}</div>}
        <h1 className="page-title">
          {title}
          {moat && <span className="moat-badge">★ The moat</span>}
        </h1>
        <p className="page-sub">{subtitle}</p>
      </header>
      {children}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="state state-loading">{label}</div>
}

export function ErrorState({ message }: { message: string }) {
  return <div className="state state-error">⚠ {message}</div>
}

interface AsyncSectionProps<T> {
  loading: boolean
  error: string | null
  data: T | null
  children: (data: T) => ReactNode
}

export function AsyncSection<T>({ loading, error, data, children }: AsyncSectionProps<T>) {
  if (loading) return <Loading />
  if (error) return <ErrorState message={error} />
  if (!data) return <ErrorState message="No data" />
  return <>{children(data)}</>
}
