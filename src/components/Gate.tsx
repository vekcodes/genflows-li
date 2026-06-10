import { useEffect, useState } from 'react'
import type { CSSProperties, FormEvent, ReactNode } from 'react'
import { clearApiKey, hasApiKey, login } from '@/services/api'
import { LogoMark } from './Logo'

/** A small password guard. Renders children only once the backend accepts the password. */
export default function Gate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(hasApiKey())
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  // If the stored password stops working mid-session, the API client fires this event.
  useEffect(() => {
    const onUnauth = () => {
      clearApiKey()
      setAuthed(false)
      setErr('Session expired — please sign in again.')
    }
    window.addEventListener('gf-unauthorized', onUnauth)
    return () => window.removeEventListener('gf-unauthorized', onUnauth)
  }, [])

  if (authed) return <>{children}</>

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!pw.trim() || busy) return
    setBusy(true)
    setErr('')
    try {
      await login(pw.trim())
      setAuthed(true)
    } catch (e) {
      setErr(e instanceof Error && e.message ? e.message : 'Incorrect password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={wrap}>
      <form onSubmit={submit} style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <LogoMark size={34} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 18 }}>GenFlows</div>
            <div style={{ color: 'var(--gf-space, #9da2b3)', fontSize: 13 }}>Content Engine</div>
          </div>
        </div>
        <div style={{ color: 'var(--gf-space, #9da2b3)', fontSize: 14 }}>
          Enter the password to continue.
        </div>
        <input
          type="password"
          autoFocus
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="Password"
          style={input}
        />
        {err && <div style={{ color: '#ff6b6b', fontSize: 13 }}>{err}</div>}
        <button type="submit" disabled={busy} style={{ ...btn, opacity: busy ? 0.7 : 1 }}>
          {busy ? 'Checking…' : 'Unlock'}
        </button>
      </form>
    </div>
  )
}

const wrap: CSSProperties = {
  minHeight: '100vh',
  display: 'grid',
  placeItems: 'center',
  padding: 24,
}
const card: CSSProperties = {
  width: 'min(360px, 92vw)',
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  background: 'var(--panel, #0e2740)',
  border: '1px solid var(--border, #1e3a5c)',
  borderRadius: 14,
  padding: 26,
  boxShadow: '0 14px 34px rgba(0,0,0,0.34)',
}
const input: CSSProperties = {
  padding: '12px 14px',
  borderRadius: 9,
  border: '1px solid var(--border-strong, #294b6e)',
  background: 'var(--bg-2, #0a1f35)',
  color: '#fff',
  fontSize: 15,
  outline: 'none',
}
const btn: CSSProperties = {
  padding: '12px 14px',
  borderRadius: 9,
  border: 'none',
  cursor: 'pointer',
  background: 'var(--accent, #e67e22)',
  color: '#0a1f35',
  fontWeight: 700,
  fontSize: 15,
}
