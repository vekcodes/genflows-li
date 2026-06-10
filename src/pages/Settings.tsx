import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createSource,
  deleteSource,
  getProfile,
  getScrapeQueue,
  getStatus,
  ingestNow,
  listSources,
  retryTranscripts,
  updateProfile,
} from '@/services/api'
import type { CreatorProfile, ScrapeJob, Source } from '@/types'
import { useAsync } from '@/hooks/useAsync'
import { Page, AsyncSection } from '@/components/Page'
import { Card, Pill, Stat, StatGrid } from '@/components/ui'

export default function Settings() {
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  const sources = useAsync(() => listSources(), [tick])
  const profile = useAsync(() => getProfile(), [])
  const status = useAsync(() => getStatus(), [tick])

  return (
    <Page
      kicker="Configuration"
      title="Settings"
      subtitle="The watchlist and your offer are saved here — the weekly agent uses them automatically, so you never paste them per run."
    >
      <div className="grid grid-2">
        <ProfileCard initial={profile.data} loading={profile.loading} error={profile.error} />
        <Card>
          <h3 className="card-h">Brain status</h3>
          <AsyncSection loading={status.loading} error={status.error} data={status.data}>
            {(s) => (
              <StatGrid>
                <Stat label="Channels" value={s.sources} />
                <Stat label="Videos" value={s.videos} />
                <Stat label="Comments" value={s.comments} />
                <Stat
                  label="Claude"
                  value={s.llm.available ? 'ready' : 'offline'}
                  hint={s.llm.provider ?? '—'}
                />
              </StatGrid>
            )}
          </AsyncSection>
        </Card>
      </div>

      <Card className="watchlist-card">
        <h3 className="card-h">Channel watchlist</h3>
        <p className="muted">Competitor channels / playlists the agent studies each week.</p>
        <AddSource onAdded={reload} />
        <AsyncSection loading={sources.loading} error={sources.error} data={sources.data}>
          {(list: Source[]) =>
            list.length === 0 ? (
              <div className="empty">No channels yet — add one above.</div>
            ) : (
              <ul className="src-list">
                {list.map((s) => (
                  <li key={s.id} className="src-row">
                    <div className="src-main">
                      <span className="src-title">{s.title || s.url}</span>
                      <span className="src-sub">
                        {s.kind}
                        {s.niche ? ` · ${s.niche}` : ''}
                        {s.last_scraped_at ? ' · scraped' : ' · not scraped yet'}
                      </span>
                    </div>
                    <div className="src-actions">
                      <button className="btn btn-ghost" onClick={() => retryTranscripts(s.id).then(reload)}>
                        Retry transcripts
                      </button>
                      <button className="btn btn-ghost" onClick={() => ingestNow(s.id).then(reload)}>
                        Re-scrape
                      </button>
                      <button
                        className="btn btn-ghost"
                        onClick={() => deleteSource(s.id).then(reload)}
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )
          }
        </AsyncSection>
      </Card>

      <ScrapeQueue trigger={tick} />
    </Page>
  )
}

function ScrapeQueue({ trigger }: { trigger: number }) {
  const [jobs, setJobs] = useState<ScrapeJob[] | null>(null)
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let alive = true
    const stop = () => {
      if (timer.current) {
        clearInterval(timer.current)
        timer.current = null
      }
    }
    const load = async () => {
      try {
        const data = await getScrapeQueue()
        if (!alive) return
        setJobs(data)
        // Only keep polling while something is actually in flight.
        if (!data.some((j) => j.status === 'queued' || j.status === 'running')) stop()
      } catch {
        /* ignore transient errors */
      }
    }
    load()
    stop()
    timer.current = setInterval(load, 2000)
    return () => {
      alive = false
      stop()
    }
  }, [trigger])

  if (!jobs || jobs.length === 0) return null
  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running')
  // Active jobs always visible; recent finished ones collapsed behind a toggle.
  const finished = jobs.filter((j) => j.status === 'done' || j.status === 'error')
  const shown = open ? [...active, ...finished].slice(0, 8) : active.length ? active : finished.slice(0, 1)

  return (
    <Card className="watchlist-card queue-card">
      <div className="card-h-row">
        <h3 className="card-h">
          Scrape queue
          {active.length > 0 && <span className="queue-active"> · {active.length} active</span>}
        </h3>
        {finished.length > 0 && (
          <button className="btn btn-ghost mine-btn" onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide history' : `History (${finished.length})`}
          </button>
        )}
      </div>
      <ul className="job-list">
        {shown.map((j) => (
          <ScrapeRow key={j.id} job={j} />
        ))}
      </ul>
    </Card>
  )
}

function ScrapeRow({ job }: { job: ScrapeJob }) {
  const tone =
    job.status === 'done' ? 'green' : job.status === 'error' ? 'red' : job.status === 'running' ? 'amber' : 'blue'
  const pct =
    job.scrape_total > 0 ? Math.round((job.scrape_done / job.scrape_total) * 100) : job.status === 'done' ? 100 : 0

  return (
    <li className="job-row">
      <div className="job-head">
        <span className="job-title">{job.source_title || job.source_url || `source ${job.source_id}`}</span>
        <Pill tone={tone}>{job.status}</Pill>
      </div>
      {(job.status === 'running' || job.status === 'queued') && (
        <div className="bar batch-bar">
          <div className="bar-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
      <div className="job-detail">
        {job.status === 'running' && `Scraping ${job.scrape_done} / ${job.scrape_total} videos`}
        {job.status === 'queued' && 'Waiting in queue…'}
        {job.status === 'done' && `Done — ${job.new_videos} new video(s)`}
        {job.status === 'error' && `⚠ ${job.message ?? 'failed'}`}
      </div>
    </li>
  )
}

function AddSource({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState('')
  const [niche, setNiche] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const add = async () => {
    if (!url.trim()) return
    setBusy(true)
    setErr(null)
    try {
      await createSource({ url: url.trim(), niche: niche.trim() || undefined })
      setUrl('')
      setNiche('')
      onAdded()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed to add')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-src">
      <input
        className="input"
        placeholder="YouTube channel / playlist / video URL"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <input
        className="input src-niche"
        placeholder="niche (optional)"
        value={niche}
        onChange={(e) => setNiche(e.target.value)}
      />
      <button className="btn" onClick={add} disabled={busy}>
        {busy ? 'Adding…' : 'Add'}
      </button>
      {err && <div className="state state-error">⚠ {err}</div>}
    </div>
  )
}

function ProfileCard({
  initial,
  loading,
  error,
}: {
  initial: CreatorProfile | null
  loading: boolean
  error: string | null
}) {
  const [form, setForm] = useState<CreatorProfile | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (initial) setForm(initial)
  }, [initial])

  const save = async () => {
    if (!form) return
    setBusy(true)
    setErr(null)
    setSaved(false)
    try {
      await updateProfile({
        offer: form.offer,
        niche: form.niche,
        n_per_week: form.n_per_week,
        target_score: form.target_score,
      })
      setSaved(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed to save')
    } finally {
      setBusy(false)
    }
  }

  if (loading || !form) {
    return (
      <Card>
        <h3 className="card-h">Creator profile</h3>
        {error ? <div className="state state-error">⚠ {error}</div> : <div className="muted">Loading…</div>}
      </Card>
    )
  }

  const set = <K extends keyof CreatorProfile>(k: K, v: CreatorProfile[K]) => {
    setForm({ ...form, [k]: v })
    setSaved(false)
  }

  return (
    <Card>
      <h3 className="card-h">Creator profile</h3>
      <label className="field-label">Your offer / booking CTA</label>
      <textarea
        className="desc-editor"
        style={{ minHeight: 80 }}
        placeholder={'What you sell + booking link, woven into every description.\ne.g. "I help editors land clients — book a free call: cal.com/you"'}
        value={form.offer}
        onChange={(e) => set('offer', e.target.value)}
      />
      <div className="grid grid-2" style={{ marginTop: 12 }}>
        <div>
          <label className="field-label">Niche</label>
          <input
            className="input"
            value={form.niche ?? ''}
            onChange={(e) => set('niche', e.target.value)}
            placeholder="e.g. video editing"
          />
        </div>
        <div>
          <label className="field-label">Ideas / week</label>
          <input
            className="input"
            type="number"
            min={1}
            max={7}
            value={form.n_per_week}
            onChange={(e) => set('n_per_week', Number(e.target.value))}
          />
        </div>
      </div>
      <div className="prof-actions">
        <button className="btn" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save profile'}
        </button>
        {saved && <span className="saved-note">✓ Saved</span>}
        {err && <span className="state state-error">⚠ {err}</span>}
      </div>
    </Card>
  )
}
