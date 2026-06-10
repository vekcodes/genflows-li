import type { AssistantStep } from '@/services/api'

const ICON: Record<string, string> = {
  pending: '○',
  running: '◌',
  done: '●',
  skipped: '—',
  error: '✕',
}

export function Steps({ steps }: { steps: AssistantStep[] }) {
  return (
    <ul className="steps">
      {steps.map((s) => (
        <li key={s.key} className={`step step-${s.status}`}>
          <span className={`step-icon${s.status === 'running' ? ' spin' : ''}`}>{ICON[s.status]}</span>
          <span className="step-label">{s.label}</span>
          {s.detail && <span className="step-detail">{s.detail}</span>}
        </li>
      ))}
    </ul>
  )
}
