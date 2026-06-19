import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getJob, getStatus, runAssistant } from '@/services/api'
import type { AssistantScript, Job } from '@/services/api'
import type { BrainStatus } from '@/types'
import { ScriptCard } from '@/components/ScriptCard'
import { Steps } from '@/components/Steps'
import { LogoMark } from '@/components/Logo'

interface Turn {
  id: string
  prompt: string
  channels: string[]
  jobId: string | null
  job: Job | null
  error: string | null
}

export default function Assistant() {
  const [channels, setChannels] = useState('')
  const [niche, setNiche] = useState('')
  const [nScripts, setNScripts] = useState(3)
  const [offer, setOffer] = useState('')
  const [prompt, setPrompt] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [status, setStatus] = useState<BrainStatus | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getStatus().then(setStatus).catch(() => {})
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns])

  // Poll any running job.
  const running = turns.find((t) => t.jobId && t.job?.status !== 'done' && t.job?.status !== 'error' && !t.error)
  useEffect(() => {
    if (!running?.jobId) return
    const id = running.jobId
    const timer = setInterval(async () => {
      try {
        const job = await getJob(id)
        setTurns((ts) => ts.map((t) => (t.jobId === id ? { ...t, job } : t)))
        if (job.status === 'done' || job.status === 'error') {
          clearInterval(timer)
          getStatus().then(setStatus).catch(() => {})
        }
      } catch (e) {
        setTurns((ts) =>
          ts.map((t) => (t.jobId === id ? { ...t, error: e instanceof ApiError ? e.message : 'lost connection' } : t)),
        )
        clearInterval(timer)
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [running?.jobId])

  const send = useCallback(async () => {
    const chans = channels.split('\n').map((c) => c.trim()).filter(Boolean)
    const text = prompt.trim() || 'Generate me some LinkedIn posts.'
    const turn: Turn = { id: crypto.randomUUID(), prompt: text, channels: chans, jobId: null, job: null, error: null }
    setTurns((ts) => [...ts, turn])
    setPrompt('')
    try {
      const { job_id } = await runAssistant({
        channels: chans,
        prompt: text,
        niche: niche.trim() || undefined,
        n_scripts: nScripts,
        offer: offer.trim() || undefined,
      })
      setTurns((ts) => ts.map((t) => (t.id === turn.id ? { ...t, jobId: job_id } : t)))
    } catch (e) {
      setTurns((ts) =>
        ts.map((t) => (t.id === turn.id ? { ...t, error: e instanceof ApiError ? e.message : 'failed to start' } : t)),
      )
    }
  }, [channels, prompt, niche, nScripts, offer])

  const busy = !!running

  return (
    <div className="assistant">
      <aside className="side">
        <div className="brand">
          <span className="brand-mark"><LogoMark size={28} /></span>
          <div>
            <div className="brand-title">GenFlows</div>
            <div className="brand-sub">LinkedIn Post Writer</div>
          </div>
        </div>

        <label className="field-label">LinkedIn profiles & pages</label>
        <textarea
          className="channels"
          placeholder={'Paste LinkedIn profile / company page URLs\n(one per line)'}
          value={channels}
          onChange={(e) => setChannels(e.target.value)}
        />

        <label className="field-label">Niche (optional)</label>
        <input className="input" value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="e.g. personal branding" />

        <label className="field-label">Posts to write</label>
        <input
          className="input"
          type="number"
          min={1}
          max={6}
          value={nScripts}
          onChange={(e) => setNScripts(Number(e.target.value))}
        />

        <label className="field-label">Your offer / booking CTA</label>
        <textarea
          className="channels"
          style={{ minHeight: 80 }}
          placeholder={'What you sell + booking link.\ne.g. "I help editors land clients — book a free call: cal.com/you"'}
          value={offer}
          onChange={(e) => setOffer(e.target.value)}
        />

        {status && (
          <div className="brain-mini">
            <div>{status.videos} posts · {status.comments} comments</div>
            <div>
              Claude:{' '}
              <span className={status.llm.available ? 'ok' : 'off'}>
                {status.llm.available ? 'ready' : 'offline'}
              </span>
            </div>
            <div>
              Daily auto-scrape:{' '}
              <span className={status.scheduler.enabled ? 'ok' : 'off'}>
                {status.scheduler.enabled ? `on · every ${status.scheduler.cadence_hours}h` : 'off'}
              </span>
            </div>
          </div>
        )}
        <div className="side-foot">Scrapes all posts · researches each idea one-by-one against the engagement model. Takes time.</div>
      </aside>

      <main className="chat-wrap">
        <div className="chat" ref={scrollRef}>
          {turns.length === 0 && (
            <div className="welcome">
              <span className="welcome-kicker">Precision-engineered · Virality-backtested</span>
              <h1>
                What should we <span className="accent">make</span>?
              </h1>
              <p className=”muted”>
                Add competitor profiles on the left, then ask — e.g.{‘ ‘}
                <em>”Generate me 3 LinkedIn posts about cold outreach.”</em> It scrapes{‘ ‘}
                <strong>all posts</strong> (text + comments), studies what performs and
                what’s trending now, then researches each idea and refines it until it clears the
                engagement bar — writing posts <strong>one at a time</strong>. This is deliberate,
                so a fresh profile can take a while.
              </p>
            </div>
          )}

          {turns.map((turn) => (
            <div key={turn.id} className="turn">
              <div className="msg user">
                <div className="bubble">
                  {turn.prompt}
                  {turn.channels.length > 0 && (
                    <div className="msg-meta">{turn.channels.length} profile(s)</div>
                  )}
                </div>
              </div>

              <div className="msg bot">
                <div className="bubble bot-bubble">
                  {turn.error && <div className="state state-error">⚠ {turn.error}</div>}
                  {!turn.error && !turn.job && <div className="muted">Starting…</div>}
                  {turn.job && <Steps steps={turn.job.steps} />}
                  {turn.job?.status === 'error' && (
                    <div className="state state-error">⚠ {turn.job.error}</div>
                  )}
                  {turn.job?.result && <Results scripts={turn.job.result.scripts} note={turn.job.result.summary.note} />}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="composer">
          <textarea
            className="composer-input"
            placeholder="Generate me some LinkedIn posts…"
            value={prompt}
            rows={1}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (!busy) send()
              }
            }}
          />
          <button className="btn send" onClick={send} disabled={busy}>
            {busy ? 'Working…' : 'Generate ▶'}
          </button>
        </div>
      </main>
    </div>
  )
}

function Results({ scripts, note }: { scripts: AssistantScript[]; note: string }) {
  if (scripts.length === 0) {
    return <div className="muted" style={{ marginTop: 8 }}>{note || 'No posts produced.'}</div>
  }
  return (
    <div className="results">
      <div className="results-note">{note}</div>
      {scripts.map((s, i) => (
        <ScriptCard key={i} script={s} index={i} />
      ))}
    </div>
  )
}
