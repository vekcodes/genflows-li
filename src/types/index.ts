// Response shapes from the LinkedIn Automation API (backend/app).

export type SourceKind = 'profile' | 'company' | 'hashtag'

export interface Source {
  id: number
  url: string
  kind: SourceKind
  external_id: string | null
  title: string | null
  niche: string | null
  cadence_hours: number
  active: boolean
  last_scraped_at: string | null
  created_at: string
}

export interface ScrapeJob {
  id: number
  source_id: number
  source_title: string | null
  source_url: string | null
  status: string // queued | running | done | error
  scrape_total: number
  scrape_done: number
  new_videos: number  // = new posts
  message: string | null
  started_at: string
  finished_at: string | null
}

export interface BrainStatus {
  sources: number
  videos: number    // = posts
  transcripts: number
  comments: number
  llm: { provider: string | null; available: boolean }
  scheduler: { enabled: boolean; cadence_hours: number; interval_minutes: number }
}

export interface Baseline {
  channel_id: string      // author_id
  channel_name: string | null
  video_count: number     // post count
  median_views: number    // median reactions
}

export interface Outlier {
  video_id: string        // post_id
  title: string           // post text excerpt
  channel_id: string      // author_id
  views: number           // reactions
  channel_median: number
  multiplier: number
}

export interface Trending {
  video_id: string        // post_id
  title: string           // post text excerpt
  channel_id: string      // author_id
  views: number           // reactions
  velocity: number        // reactions per day
  multiplier: number
  published_at: string
}

export interface BacktestReport {
  status: 'ok' | 'insufficient_data' | 'error'
  n: number
  viral_threshold: number
  message?: string
  n_train?: number
  n_test?: number
  n_viral?: number
  base_rate?: number
  roc_auc?: number | null
  precision_at_k?: number
  k?: number
  lift_at_k?: number | null
  spearman_corr?: number | null
  top_features?: { feature: string; weight: number }[]
}

export interface PainPoint {
  id: number
  niche: string | null
  question: string
  frequency: number
  example: string | null
}

export interface FormatPattern {
  id: number
  niche: string | null
  label: string
  description: string
  avg_multiplier: number
  example_video_ids: string[]   // post IDs
}

export interface StyleCard {
  channel_id: string    // author_id
  channel_name: string | null
  tone: string
  pacing: string
  hooks: string[]
  vocabulary: string[]
}

export interface ContentGap {
  question: string
  frequency: number
  coverage: number
  covered: boolean
}

export interface Analog {
  video_id: string    // post_id
  title: string       // post text excerpt
  multiplier: number
}

export interface Idea {
  title: string       // hook / opening line
  angle: string
  format: string
  evidence: string[]
  virality_score: number | null
  predicted_viral: boolean | null
  nearest_analogs: Analog[]
  model_status: string
}

export interface IdeasResult {
  model_trained: boolean
  viral_threshold: number
  min_score: number
  count: number
  ideas: Idea[]
}

export interface ScriptSection {
  beat: string
  heading: string
  intent: string
  content: string
}

export interface Script {
  title: string
  sections: ScriptSection[]
  markdown: string
}

export interface Demand {
  keyword: string
  trends: {
    available: boolean
    interest?: number
    direction?: 'rising' | 'flat' | 'falling'
    history?: number[]
    reason?: string
  }
  suggestions: string[]
}

export interface SearchHit {
  video_id: string    // post_id
  idx: number
  score: number
  text: string
}

// ---- Agentic content engine ----

export type ContentStatus =
  | 'proposed'
  | 'approved'
  | 'declined'
  | 'scheduled'
  | 'published'
  | 'scored'
  | 'archived'

export interface ContentItem {
  id: number
  batch_id: string
  status: ContentStatus
  title: string             // hook / opening line of the post
  angle: string
  format: string
  script_markdown: string   // full LinkedIn post text
  description: string       // first-comment CTA
  thumbnail_prompt: string  // image/visual prompt
  evidence: string[]
  sections: { beat: string; heading: string; intent?: string; content?: string }[]
  predicted_score: number | null
  predicted_viral: boolean | null
  nearest_analogs: Analog[]
  channel_id: string | null   // author_id
  niche: string | null
  scheduled_for: string | null
  declined_reason: string | null
  regenerated_from_id: number | null
  published_video_id: string | null   // post URN after publishing
  published_url: string | null
  published_at: string | null
  actual_multiplier: number | null
  performed: boolean | null
  reward: number | null
  created_at: string
  updated_at: string
}

export interface ContentRun {
  id: number
  batch_id: string
  status: string
  phase: string   // queued | scraping | mining | writing | done
  scrape_total: number
  scrape_done: number
  n_requested: number
  n_done: number
  message: string | null
  started_at: string
  finished_at: string | null
}

export interface CreatorProfile {
  id: number
  offer: string
  niche: string | null
  n_per_week: number
  target_score: number
  duration_sec: number
  updated_at: string
}
