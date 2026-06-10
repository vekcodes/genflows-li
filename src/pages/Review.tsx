import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getQueue } from '@/services/api'
import type { ContentItem, ContentStatus } from '@/types'
import { useAsync } from '@/hooks/useAsync'
import { Page, AsyncSection } from '@/components/Page'
import { ContentCard } from '@/components/ContentCard'

const FILTERS: { key: string; label: string; match: (s: ContentStatus) => boolean }[] = [
  { key: 'actionable', label: 'Needs you', match: (s) => s === 'proposed' || s === 'approved' || s === 'scheduled' || s === 'published' },
  { key: 'proposed', label: 'Proposed', match: (s) => s === 'proposed' },
  { key: 'scored', label: 'Scored', match: (s) => s === 'scored' },
  { key: 'all', label: 'All', match: () => true },
]

export default function Review() {
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  const { data, loading, error } = useAsync(() => getQueue(), [tick])
  const [filter, setFilter] = useState('actionable')
  const [params] = useSearchParams()
  const focusId = params.get('focus')
  const focusRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (focusId && focusRef.current) {
      focusRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [focusId, data])

  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0]

  return (
    <Page
      kicker="Review & feedback"
      title="Review Queue"
      subtitle="Approve what's strong, decline what isn't (with a reason — the agent learns from it), and mark items published so the engine can measure real performance."
    >
      <div className="filter-row">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip-btn${filter === f.key ? ' active' : ''}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <AsyncSection loading={loading} error={error} data={data}>
        {(items: ContentItem[]) => {
          const shown = items.filter((i) => active.match(i.status))
          if (shown.length === 0)
            return <div className="empty">Nothing here yet. Generate a batch from the Calendar.</div>
          return (
            <div className="review-list">
              {shown.map((it) => (
                <div key={it.id} ref={String(it.id) === focusId ? focusRef : undefined}>
                  <ContentCard item={it} onChanged={reload} />
                </div>
              ))}
            </div>
          )
        }}
      </AsyncSection>
    </Page>
  )
}
