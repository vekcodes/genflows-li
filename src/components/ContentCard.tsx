import { useState } from 'react'
import type { ContentItem } from '@/types'
import { approveItem, declineItem, publishItem, rescoreItems } from '@/services/api'
import { Pill } from './ui'

function scoreTone(score: number | null): string {
  if (score === null) return 'blue'
  return score >= 66 ? 'green' : score >= 40 ? 'amber' : 'red'
}

const STATUS_TONE: Record<string, string> = {
  proposed: 'blue',
  approved: 'cyan',
  scheduled: 'cyan',
  published: 'amber',
  scored: 'green',
  declined: 'red',
  archived: 'default',
}

/** One content package with the actions appropriate to its status. `onChanged` reloads the list. */
export function ContentCard({ item, onChanged }: { item: ContentItem; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [url, setUrl] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'action failed')
    } finally {
      setBusy(false)
    }
  }

  const copy = (text: string) => navigator.clipboard?.writeText(text)

  return (
    <div className="c-detail card">
      <div className="c-detail-head">
        <span className={`score-badge score-${scoreTone(item.predicted_score)}`}>
          {item.predicted_score ?? '—'}
        </span>
        <div className="c-detail-titlewrap">
          <div className="c-detail-title">{item.title}</div>
          <div className="c-detail-sub">{item.angle}</div>
        </div>
        <Pill tone={STATUS_TONE[item.status] ?? 'default'}>{item.status}</Pill>
      </div>

      <div className="c-detail-meta">
        <Pill tone="blue">{item.format}</Pill>
        {item.predicted_viral && <Pill tone="green">likely viral</Pill>}
        {item.evidence.map((e, i) => (
          <Pill key={i} tone="purple">
            {e}
          </Pill>
        ))}
      </div>

      {item.status === 'scored' && (
        <div className={`perf ${item.performed ? 'perf-win' : 'perf-loss'}`}>
          {item.performed ? '✓ Performed' : '✗ Underperformed'} — actual{' '}
          <strong>{item.actual_multiplier}×</strong> vs predicted {item.predicted_score}
        </div>
      )}
      {item.status === 'published' && (
        <div className="perf perf-pending">Published — measuring performance as views accrue…</div>
      )}
      {item.declined_reason && (
        <div className="perf perf-loss">Declined: {item.declined_reason}</div>
      )}

      <button className="c-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? '▾ Hide' : '▸ Show'} script, description & thumbnail
      </button>

      {open && (
        <div className="c-body">
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">Thumbnail prompt</span>
              <button className="btn btn-ghost" onClick={() => copy(item.thumbnail_prompt)}>
                ⧉ Copy
              </button>
            </div>
            <div className="title-box">{item.thumbnail_prompt}</div>
          </div>
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">YouTube description + CTA</span>
              <button className="btn btn-ghost" onClick={() => copy(item.description)}>
                ⧉ Copy
              </button>
            </div>
            <pre className="c-pre">{item.description}</pre>
          </div>
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">Script</span>
              <button className="btn btn-ghost" onClick={() => copy(item.script_markdown)}>
                ⧉ Copy
              </button>
            </div>
            <pre className="c-pre c-script">{item.script_markdown}</pre>
          </div>
        </div>
      )}

      {err && <div className="state state-error">⚠ {err}</div>}

      {/* Status-appropriate actions */}
      <div className="c-actions">
        {item.status === 'proposed' && !declining && (
          <>
            <button className="btn" disabled={busy} onClick={() => run(() => approveItem(item.id))}>
              ✓ Approve
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => setDeclining(true)}>
              ✗ Decline & regenerate
            </button>
          </>
        )}

        {declining && (
          <div className="c-inline">
            <textarea
              className="desc-editor"
              style={{ minHeight: 64 }}
              placeholder="Why decline? The agent uses this to generate a better replacement…"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="c-actions">
              <button
                className="btn"
                disabled={busy || !reason.trim()}
                onClick={() =>
                  run(() => declineItem(item.id, reason.trim())).then(() => {
                    setDeclining(false)
                    setReason('')
                  })
                }
              >
                Submit & regenerate
              </button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setDeclining(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {(item.status === 'approved' || item.status === 'scheduled') &&
          (publishing ? (
            <div className="c-inline">
              <input
                className="input"
                placeholder="Published YouTube URL (https://youtu.be/…)"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <div className="c-actions">
                <button
                  className="btn"
                  disabled={busy || !url.trim()}
                  onClick={() =>
                    run(() => publishItem(item.id, url.trim())).then(() => setPublishing(false))
                  }
                >
                  Mark published & measure
                </button>
                <button className="btn btn-ghost" disabled={busy} onClick={() => setPublishing(false)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button className="btn" disabled={busy} onClick={() => setPublishing(true)}>
              ▶ Mark published (add URL)
            </button>
          ))}

        {item.status === 'published' && (
          <button className="btn btn-ghost" disabled={busy} onClick={() => run(() => rescoreItems())}>
            ↻ Re-measure now
          </button>
        )}
      </div>
    </div>
  )
}
