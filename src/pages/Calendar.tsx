import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { generateBatch, generateOnCommand, getQueue, getRun } from '@/services/api'
import type { ContentItem, ContentRun } from '@/types'
import { useAsync } from '@/hooks/useAsync'
import { Page, AsyncSection } from '@/components/Page'
import { Pill } from '@/components/ui'

const COLUMNS: { key: string; label: string; match: (s: string) => boolean }[] = [
  { key: 'proposed', label: 'Proposed', match: (s) => s === 'proposed' },
  { key: 'approved', label: 'Approved · Scheduled', match: (s) => s === 'approved' || s === 'scheduled' },
  { key: 'published', label: 'Published', match: (s) => s === 'published' },
  { key: 'scored', label: 'Scored', match: (s) => s === 'scored' },
]

function scoreClass(score: number | null): string {
  if (score === null) return 'score-blue'
  return score >= 66 ? 'score-green' : score >= 40 ? 'score-amber' : 'score-red'
}

const PHASE_LABEL: Record<string, string> = {
  queued: 'Starting…',
  scraping: 'Scraping videos',
  mining: 'Mining insights',
  writing: 'Writing scripts',
  done: 'Done',
}

function BatchProgress({ run }: { run: ContentRun }) {
  const done = run.status === 'done' || run.phase === 'done'
  let pct = 0
  let detail = run.message || ''
  if (run.phase === 'scraping' && run.scrape_total > 0) {
    pct = Math.round((run.scrape_done / run.scrape_total) * 100)
    detail = `${run.scrape_done} / ${run.scrape_total} videos`
  } else if (run.phase === 'writing' && run.n_requested > 0) {
    pct = Math.round((run.n_done / run.n_requested) * 100)
    detail = run.message
      ? `${run.n_done}/${run.n_requested} done · ${run.message}`
      : `${run.n_done} / ${run.n_requested} ideas written`
  } else if (run.phase === 'mining') {
    pct = 50
  } else if (done) {
    pct = 100
    detail = `${run.n_done} idea(s) added`
  }

  return (
    <div className="batch-progress">
      <div className="batch-progress-head">
        <span className="batch-phase">
          {done ? '✓ ' : ''}
          {PHASE_LABEL[run.phase] ?? run.phase}
        </span>
        <span className="batch-detail">{detail}</span>
      </div>
      <div className="bar batch-bar">
        <div
          className={`bar-fill${((run.phase === 'mining' || run.phase === 'writing') && !done) ? ' indeterminate' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function Calendar() {
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  const { data, loading, error } = useAsync(() => getQueue(), [tick])
  const [run, setRun] = useState<ContentRun | null>(null)
  const [genErr, setGenErr] = useState<string | null>(null)
  const [topic, setTopic] = useState('')
  // When true, the batch button writes straight from the existing Brain (no re-scrape) — fast.
  const [fast, setFast] = useState(true)
  const navigate = useNavigate()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const busy = run != null && run.status === 'running'

  const generate = useCallback(
    async (onCommandTopic?: string) => {
      setGenErr(null)
      try {
        const { batch_id, n_requested } = onCommandTopic
          ? await generateOnCommand(onCommandTopic)
          : await generateBatch(undefined, !fast)
        setRun({
          id: 0, batch_id, status: 'running', phase: 'queued',
          scrape_total: 0, scrape_done: 0, n_requested, n_done: 0,
          message: null, started_at: '', finished_at: null,
        })
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(async () => {
          try {
            const r = await getRun(batch_id)
            setRun(r)
            reload()
            if (r.status !== 'running' && pollRef.current) clearInterval(pollRef.current)
          } catch {
            /* keep polling */
          }
        }, 2000)
      } catch (e) {
        setGenErr(e instanceof Error ? e.message : 'failed to start')
      }
    },
    [reload, fast],
  )

  const runOnCommand = () => {
    const t = topic.trim()
    if (!t || busy) return
    setTopic('')
    generate(t)
  }

  return (
    <Page
      kicker="Autonomous content engine"
      title="Content Calendar"
      subtitle="Every week the agent researches your channels, clears the virality bar, and drops a fresh batch here. Review, approve, publish — it learns from what you ship."
    >
      <div className="cal-toolbar">
        <button className="btn" onClick={() => generate()} disabled={busy}>
          {busy ? 'Working…' : fast ? '✨ Generate batch (use brain)' : '✨ Generate this week’s batch'}
        </button>
        <label className="fast-toggle" title="Skip re-scraping and write straight from the Brain you already have.">
          <input type="checkbox" checked={fast} onChange={(e) => setFast(e.target.checked)} disabled={busy} />
          <span>Use brain (fast — no re-scrape)</span>
        </label>
        <div className="oncommand">
          <input
            className="input"
            placeholder="…or generate one video about a specific topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runOnCommand()}
            disabled={busy}
          />
          <button className="btn btn-ghost" onClick={runOnCommand} disabled={busy || !topic.trim()}>
            Generate
          </button>
        </div>
      </div>
      {genErr && <div className="state state-error">⚠ {genErr}</div>}

      {run && <BatchProgress run={run} />}

      <AsyncSection loading={loading} error={error} data={data}>
        {(items: ContentItem[]) => (
          <div className="board">
            {COLUMNS.map((col) => {
              const cards = items.filter((i) => col.match(i.status))
              return (
                <div className="board-col" key={col.key}>
                  <div className="board-col-head">
                    <span>{col.label}</span>
                    <span className="board-count">{cards.length}</span>
                  </div>
                  {cards.length === 0 && <div className="board-empty">—</div>}
                  {cards.map((it) => (
                    <button
                      key={it.id}
                      className="c-card"
                      onClick={() => navigate(`/review?focus=${it.id}`)}
                    >
                      <div className="c-card-title">{it.title}</div>
                      <div className="c-card-meta">
                        <span className={`score-badge ${scoreClass(it.predicted_score)}`}>
                          {it.predicted_score ?? '—'}
                        </span>
                        <Pill tone="blue">{it.format}</Pill>
                        {it.status === 'scored' && (
                          <Pill tone={it.performed ? 'green' : 'red'}>
                            {it.actual_multiplier}× actual
                          </Pill>
                        )}
                        {it.scheduled_for && <span className="c-card-date">{it.scheduled_for}</span>}
                      </div>
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        )}
      </AsyncSection>
    </Page>
  )
}
