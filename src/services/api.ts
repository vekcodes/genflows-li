// Typed client for the Brain API. Point at the backend with VITE_API_BASE_URL
// (defaults to localhost:8000 for dev). Optional VITE_API_KEY sets X-API-Key.

import type {
  Analog,
  Baseline,
  BacktestReport,
  BrainStatus,
  ContentGap,
  ContentItem,
  ContentRun,
  ContentStatus,
  CreatorProfile,
  Demand,
  FormatPattern,
  IdeasResult,
  Outlier,
  PainPoint,
  ScrapeJob,
  Trending,
  Script,
  SearchHit,
  Source,
  StyleCard,
} from '@/types'

const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// --- Password guard ---------------------------------------------------------
// The backend gates the data/generation API behind BRAIN_API_KEY. The user types the
// password on the login screen; we persist it and send it as X-API-Key on every request.
// The password is never baked into the bundle. A build-time VITE_API_KEY (if set) is the
// fallback for open local dev.
const KEY_STORAGE = 'gf_api_key'
const apiKey = () => localStorage.getItem(KEY_STORAGE) || (import.meta.env.VITE_API_KEY ?? '')
export const hasApiKey = () => !!localStorage.getItem(KEY_STORAGE)
export const setApiKey = (k: string) => localStorage.setItem(KEY_STORAGE, k)
export const clearApiKey = () => localStorage.removeItem(KEY_STORAGE)

/** Validate a candidate password against the backend; persist it only on success. */
export async function login(password: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${BASE}/brain/status`, { headers: { 'x-api-key': password } })
  } catch {
    throw new ApiError(0, `Cannot reach the server at ${BASE}.`)
  }
  if (res.status === 401) throw new ApiError(401, 'Incorrect password.')
  if (!res.ok) throw new ApiError(res.status, `Server error (${res.status}).`)
  setApiKey(password)
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  if (init.body) headers['content-type'] = 'application/json'
  const key = apiKey()
  if (key) headers['x-api-key'] = key

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, `Cannot reach the Brain API at ${BASE}. Is the backend running?`)
  }
  if (!res.ok) {
    // Stored password no longer accepted → bounce back to the login screen.
    if (res.status === 401) {
      clearApiKey()
      window.dispatchEvent(new Event('gf-unauthorized'))
    }
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const qs = (params: Record<string, unknown>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') u.set(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

// ---- Sources / ingestion ----
export const listSources = () => req<Source[]>('/sources')
export const createSource = (body: { url: string; niche?: string }, ingest = true) =>
  req<Source>(`/sources${qs({ ingest })}`, { method: 'POST', body: JSON.stringify(body) })
export const deleteSource = (id: number) => req<void>(`/sources/${id}`, { method: 'DELETE' })
export const ingestNow = (id: number) =>
  req<ScrapeJob>(`/sources/${id}/ingest`, { method: 'POST' })
export const getScrapeQueue = () => req<ScrapeJob[]>('/sources/queue')

// ---- Brain ----
export const getStatus = () => req<BrainStatus>('/brain/status')
export const getBaselines = () => req<Baseline[]>('/brain/baselines')
export const getOutliers = (minMultiplier = 1, limit = 50) =>
  req<Outlier[]>(`/brain/outliers${qs({ min_multiplier: minMultiplier, limit })}`)
export const getTrending = (limit = 10) => req<Trending[]>(`/brain/trending${qs({ limit })}`)
export const getBacktest = (viralThreshold = 2) =>
  req<BacktestReport>(`/brain/virality/backtest${qs({ viral_threshold: viralThreshold })}`)

export const getPainPoints = (niche?: string) =>
  req<PainPoint[]>(`/brain/pain-points${qs({ niche })}`)
export const getPatterns = (niche?: string) => req<FormatPattern[]>(`/brain/patterns${qs({ niche })}`)
export const getStyleCards = () => req<StyleCard[]>('/brain/style-cards')
export const getContentGaps = (niche?: string) =>
  req<ContentGap[]>(`/brain/content-gaps${qs({ niche })}`)

export const minePainPoints = (niche?: string) =>
  req<PainPoint[]>(`/brain/mine/pain-points${qs({ niche })}`, { method: 'POST' })
export const minePatterns = (minMultiplier = 3) =>
  req<FormatPattern[]>(`/brain/mine/patterns${qs({ min_multiplier: minMultiplier })}`, { method: 'POST' })
export const mineStyleCard = (channelId: string) =>
  req<StyleCard>(`/brain/mine/style-card${qs({ channel_id: channelId })}`, { method: 'POST' })

export const getDemand = (keyword: string) => req<Demand>(`/brain/demand${qs({ keyword })}`)
export const search = (q: string, k = 8) => req<SearchHit[]>(`/brain/search${qs({ q, k })}`)

// ---- Generation ----
export interface IdeasBody {
  channel_id?: string
  niche?: string
  n?: number
  duration_sec?: number
  min_score?: number
  top?: number
  viral_threshold?: number
}
export const generateIdeas = (body: IdeasBody) =>
  req<IdeasResult>('/generate/ideas', { method: 'POST', body: JSON.stringify(body) })

export interface ScriptBody {
  title: string
  angle?: string
  channel_id?: string
  polish?: boolean
}
export const generateScript = (body: ScriptBody) =>
  req<Script>('/generate/script', { method: 'POST', body: JSON.stringify(body) })

// ---- Assistant (one-shot: channels + prompt -> whole pipeline -> scripts) ----
export interface AssistantStep {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'skipped' | 'error'
  detail: string
}
export interface AssistantScript {
  title: string
  angle: string
  format: string
  virality_score: number | null
  predicted_viral: boolean | null
  evidence: string[]
  nearest_analogs: Analog[]
  description: string
  markdown: string
  sections: { beat: string; heading: string; content: string }[]
}
export interface AssistantResult {
  scripts: AssistantScript[]
  summary: {
    new_videos: number
    videos: number
    outliers: { title: string; multiplier: number }[]
    llm: boolean
    note: string
  }
}
export interface Job {
  id: string
  prompt: string
  status: 'running' | 'done' | 'error'
  steps: AssistantStep[]
  result: AssistantResult | null
  error: string | null
}

export interface RunBody {
  channels: string[]
  prompt: string
  niche?: string
  n_scripts?: number
  target_score?: number
  offer?: string
}
export const runAssistant = (body: RunBody) =>
  req<{ job_id: string }>('/assistant/run', { method: 'POST', body: JSON.stringify(body) })
export const getJob = (id: string) => req<Job>(`/assistant/jobs/${id}`)

// ---- Agentic content engine (queue / calendar + review actions) ----
export const getQueue = (status?: ContentStatus) =>
  req<ContentItem[]>(`/content/queue${qs({ status })}`)
export const getItem = (id: number) => req<ContentItem>(`/content/${id}`)
// refresh=true re-scrapes every source first (weekly job). refresh=false skips the scrape and
// writes straight from the existing Brain — the "use brain (fast)" path.
export const generateBatch = (n?: number, refresh = true) =>
  req<{ batch_id: string; n_requested: number }>(
    `/content/generate${qs({ n, refresh })}`,
    { method: 'POST' },
  )
// On-command: a specific topic, one item, no re-scrape (uses existing Brain data → fast).
export const generateOnCommand = (topic: string) =>
  req<{ batch_id: string; n_requested: number }>(
    `/content/generate${qs({ n: 1, topic, refresh: false })}`,
    { method: 'POST' },
  )
export const getRun = (batchId: string) => req<ContentRun>(`/content/runs/${batchId}`)
export const approveItem = (id: number) =>
  req<ContentItem>(`/content/${id}/approve`, { method: 'POST' })
export const declineItem = (id: number, reason: string) =>
  req<ContentItem>(`/content/${id}/decline`, { method: 'POST', body: JSON.stringify({ reason }) })
export const scheduleItem = (id: number, when: string) =>
  req<ContentItem>(`/content/${id}/schedule`, { method: 'POST', body: JSON.stringify({ when }) })
export const publishItem = (id: number, url: string) =>
  req<ContentItem>(`/content/${id}/publish`, { method: 'POST', body: JSON.stringify({ url }) })
export const rescoreItems = () => req<{ updated: number }>('/content/rescore', { method: 'POST' })
export const getProfile = () => req<CreatorProfile>('/content/profile')
export const updateProfile = (body: Partial<CreatorProfile>) =>
  req<CreatorProfile>('/content/profile', { method: 'PUT', body: JSON.stringify(body) })
