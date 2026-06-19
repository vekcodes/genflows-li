import { useState } from 'react'
import type { AssistantScript } from '@/services/api'
import { Pill } from './ui'

function scoreTone(score: number | null) {
  if (score === null) return 'blue'
  return score >= 66 ? 'green' : score >= 40 ? 'amber' : 'red'
}

export function ScriptCard({ script, index }: { script: AssistantScript; index: number }) {
  const [open, setOpen] = useState(index === 0)
  const [desc, setDesc] = useState(script.description)
  const [draft, setDraft] = useState(script.markdown)

  const fullMarkdown = () =>
    `# ${script.title}\n\n## First comment CTA\n\n${desc}\n\n## LinkedIn post\n\n${draft}\n`

  const copy = (text: string) => navigator.clipboard?.writeText(text)

  const download = () => {
    const blob = new Blob([fullMarkdown()], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${script.title.replace(/[^\w]+/g, '-').toLowerCase()}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="script-card">
      <button className="script-head" onClick={() => setOpen((o) => !o)}>
        <span className="script-toggle">{open ? '▾' : '▸'}</span>
        <Pill tone={scoreTone(script.virality_score)}>{script.virality_score ?? '—'}</Pill>
        <span className="script-title">{script.title}</span>
        {script.predicted_viral && <Pill tone="green">likely viral</Pill>}
      </button>

      {open && (
        <div className="script-body">
          {script.angle && <p className="muted">{script.angle}</p>}
          <div className="evidence">
            <Pill tone="blue">{script.format}</Pill>
            {script.evidence.map((e, j) => (
              <Pill key={j} tone="purple">
                {e}
              </Pill>
            ))}
          </div>
          {script.nearest_analogs.length > 0 && (
            <div className="muted analogs">
              closest proven: {script.nearest_analogs.map((a) => `${a.title} (${a.multiplier}×)`).join(' · ')}
            </div>
          )}

          {/* Hook */}
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">Post hook</span>
              <button className="btn btn-ghost" onClick={() => copy(script.title)}>⧉ Copy</button>
            </div>
            <div className="title-box">{script.title}</div>
          </div>

          {/* LinkedIn post */}
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">LinkedIn post</span>
              <span className="beats">
                {script.sections.map((s, i) => (
                  <Pill key={i} tone="default">
                    {s.beat}
                  </Pill>
                ))}
              </span>
            </div>
            <textarea
              className="script-editor"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
            />
          </div>

          {/* First comment CTA */}
          <div className="deliverable">
            <div className="deliverable-head">
              <span className="deliverable-label">First comment CTA</span>
              <button className="btn btn-ghost" onClick={() => copy(desc)}>⧉ Copy</button>
            </div>
            <textarea
              className="desc-editor"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              spellCheck={false}
            />
          </div>

          <div className="script-actions" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
            <button className="btn btn-ghost" onClick={() => { setDesc(script.description); setDraft(script.markdown) }}>
              ↺ Reset
            </button>
            <button className="btn" onClick={download}>↓ Export .md (hook + post + CTA)</button>
          </div>
        </div>
      )}
    </div>
  )
}
