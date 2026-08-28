import { useCallback, useEffect, useRef, useState } from 'react'
import type { ContentImage, ContentItem } from '@/types'
import { fetchItemImage, generateItemImage } from '@/services/api'

/** LinkedIn's own recommended single-image sizes. */
const SIZES = {
  square: { label: 'Square 1200×1200', width: 1200, height: 1200 },
  landscape: { label: 'Landscape 1200×628', width: 1200, height: 628 },
} as const
type SizeKey = keyof typeof SIZES

const NAVY = '#0A1F35'
const ORANGE = '#E67E22'
const WHITE = '#FFFFFF'
const HEADLINE_FONT = "'Manrope', system-ui, sans-serif"

const norm = (w: string) => w.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase()

/** Greedy word-wrap at the given font size; null when it needs more than `maxLines`. */
function wrap(
  ctx: CanvasRenderingContext2D,
  words: string[],
  maxWidth: number,
  maxLines: number,
): string[] | null {
  const lines: string[] = []
  let line = ''
  for (const word of words) {
    const next = line ? `${line} ${word}` : word
    if (ctx.measureText(next).width <= maxWidth || !line) {
      line = next
    } else {
      lines.push(line)
      line = word
    }
    if (ctx.measureText(line).width > maxWidth) return null // a single word overflows
  }
  if (line) lines.push(line)
  return lines.length <= maxLines ? lines : null
}

/**
 * Composite the brand headline onto the generated background.
 *
 * The image model is asked for a text-free visual on purpose — open models garble typography —
 * so the 2–4 word headline is drawn here in Manrope 800, white with one word in brand orange.
 * What you see on this canvas is exactly what the Download button saves.
 */
function paint(
  canvas: HTMLCanvasElement,
  img: HTMLImageElement,
  opts: { headline: string; accent: string; overlay: boolean; width: number; height: number },
) {
  // Always compose at the LinkedIn target size: free endpoints return whatever they feel like
  // (Cloudflare is a fixed 1024 square, Pollinations' anonymous tier caps at 768), and the
  // download has to be feed-spec either way. The background is cover-cropped, never squashed.
  const W = opts.width
  const H = opts.height
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.imageSmoothingQuality = 'high'
  ctx.fillStyle = NAVY
  ctx.fillRect(0, 0, W, H)
  const iw = img.naturalWidth || W
  const ih = img.naturalHeight || H
  const scale = Math.max(W / iw, H / ih)
  ctx.drawImage(img, (W - iw * scale) / 2, (H - ih * scale) / 2, iw * scale, ih * scale)

  const headline = opts.headline.trim().toUpperCase()
  if (!opts.overlay || !headline) return

  const pad = Math.round(W * 0.07)
  const maxWidth = W - pad * 2
  const words = headline.split(/\s+/)

  let size = Math.round(W * 0.1)
  let lines: string[] | null = null
  while (size > 18) {
    ctx.font = `800 ${size}px ${HEADLINE_FONT}`
    lines = wrap(ctx, words, maxWidth, 3)
    if (lines) break
    size -= 4
  }
  if (!lines) return

  const lineHeight = Math.round(size * 1.12)
  const ruleH = Math.max(6, Math.round(W * 0.007))
  const blockH = lines.length * lineHeight + ruleH + Math.round(size * 0.45)
  const blockTop = H - pad - blockH

  // Scrim so the headline stays readable over any generated background.
  const scrim = ctx.createLinearGradient(0, blockTop - pad * 1.2, 0, H)
  scrim.addColorStop(0, 'rgba(10,31,53,0)')
  scrim.addColorStop(0.45, 'rgba(10,31,53,0.72)')
  scrim.addColorStop(1, 'rgba(10,31,53,0.94)')
  ctx.fillStyle = scrim
  ctx.fillRect(0, blockTop - pad * 1.2, W, H - blockTop + pad * 1.2)

  ctx.fillStyle = ORANGE
  ctx.fillRect(pad, blockTop, Math.round(W * 0.09), ruleH)

  ctx.font = `800 ${size}px ${HEADLINE_FONT}`
  ctx.textBaseline = 'top'
  const accent = norm(opts.accent)
  let y = blockTop + ruleH + Math.round(size * 0.45)
  for (const line of lines) {
    let x = pad
    const tokens = line.split(' ')
    tokens.forEach((token, i) => {
      const text = i === tokens.length - 1 ? token : `${token} `
      ctx.fillStyle = accent && norm(token) === accent ? ORANGE : WHITE
      ctx.fillText(text, x, y)
      x += ctx.measureText(text).width
    })
    y += lineHeight
  }
}

/**
 * The post visual: rendered server-side by a free FLUX endpoint, finished in-browser with the
 * brand headline, and downloadable as a LinkedIn-ready PNG.
 */
export function PostImage({ item }: { item: ContentItem }) {
  const [meta, setMeta] = useState<ContentImage | null>(item.image)
  const [src, setSrc] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [overlay, setOverlay] = useState(true)
  const [headline, setHeadline] = useState(item.image?.overlay_text ?? '')
  const [size, setSize] = useState<SizeKey>(
    item.image && item.image.height < item.image.width ? 'landscape' : 'square',
  )
  const [editingPrompt, setEditingPrompt] = useState(false)
  const [prompt, setPrompt] = useState(item.image?.prompt || item.thumbnail_prompt)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const srcRef = useRef<string | null>(null)

  // Load the bytes (the image route is behind the API-key gate, so <img src> can't fetch it).
  const load = useCallback(async () => {
    setErr(null)
    try {
      const url = await fetchItemImage(item.id)
      if (srcRef.current) URL.revokeObjectURL(srcRef.current)
      srcRef.current = url
      setSrc(url)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'could not load the image')
    }
  }, [item.id])

  useEffect(() => {
    if (meta?.status === 'ready') void load()
  }, [meta?.status, meta?.updated_at, load])

  // Release the object URL when the card unmounts.
  useEffect(
    () => () => {
      if (srcRef.current) URL.revokeObjectURL(srcRef.current)
      srcRef.current = null
    },
    [],
  )

  // Draw whenever the background or the overlay settings change.
  const compose = useCallback(async () => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img || !img.complete) return
    try {
      await document.fonts?.load(`800 100px 'Manrope'`)
    } catch {
      /* fall back to the system sans */
    }
    paint(canvas, img, {
      headline,
      accent: meta?.accent_word ?? '',
      overlay,
      width: SIZES[size].width,
      height: SIZES[size].height,
    })
  }, [headline, overlay, size, meta?.accent_word])

  useEffect(() => {
    void compose()
  }, [src, compose])

  const generate = async (override?: { prompt?: string }) => {
    setBusy(true)
    setErr(null)
    try {
      const row = await generateItemImage(item.id, {
        ...override,
        overlay_text: headline || undefined,
        width: SIZES[size].width,
        height: SIZES[size].height,
      })
      setMeta(row)
      if (!headline) setHeadline(row.overlay_text)
      setPrompt(row.prompt)
      setEditingPrompt(false)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'image generation failed')
    } finally {
      setBusy(false)
    }
  }

  const withBlob = async (fn: (blob: Blob) => void | Promise<void>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/png'))
    if (blob) await fn(blob)
  }

  const download = () =>
    withBlob((blob) => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `linkedin-post-${item.id}.png`
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 5000)
    })

  const copyImage = () =>
    withBlob(async (blob) => {
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
        setErr(null)
      } catch {
        setErr('This browser blocks image copy — use Download instead.')
      }
    })

  const ready = meta?.status === 'ready' && !!src

  return (
    <div className="deliverable">
      <div className="deliverable-head">
        <span className="deliverable-label">Post image</span>
        {meta?.provider && (
          <span className="img-provider">
            {meta.provider} · {meta.model} · {meta.width}×{meta.height}
          </span>
        )}
      </div>

      {ready ? (
        <div className="img-frame">
          <canvas ref={canvasRef} className="img-canvas" />
          {/* Hidden source bitmap; the canvas above is what gets shown and downloaded. */}
          <img
            ref={imgRef}
            src={src}
            alt=""
            hidden
            onLoad={() => {
              void compose()
            }}
          />
        </div>
      ) : (
        <div className="img-empty">
          {busy
            ? 'Rendering with a free FLUX model…'
            : meta?.status === 'error'
              ? `No image yet — ${meta.error}`
              : 'No image yet. Render one from the prompt below.'}
        </div>
      )}

      <div className="img-controls">
        <label className="img-field">
          <span>Headline burned onto the image</span>
          <input
            className="input"
            value={headline}
            placeholder="2–4 words, e.g. STOP GUESSING"
            onChange={(e) => setHeadline(e.target.value)}
          />
        </label>
        <label className="img-check">
          <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
          Show headline
        </label>
        <label className="img-check">
          <select
            className="input"
            value={size}
            onChange={(e) => setSize(e.target.value as SizeKey)}
          >
            {Object.entries(SIZES).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="c-actions">
        <button className="btn" disabled={busy} onClick={() => void generate()}>
          {ready ? '↻ Re-render image' : '✦ Render image (free)'}
        </button>
        {ready && (
          <>
            <button className="btn" disabled={busy} onClick={() => void download()}>
              ⬇ Download PNG
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => void copyImage()}>
              ⧉ Copy image
            </button>
          </>
        )}
        <button className="btn btn-ghost" onClick={() => setEditingPrompt((v) => !v)}>
          {editingPrompt ? 'Hide prompt' : 'Edit prompt'}
        </button>
      </div>

      {editingPrompt && (
        <div className="c-inline">
          <textarea
            className="desc-editor"
            style={{ minHeight: 96 }}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="c-actions">
            <button
              className="btn"
              disabled={busy || !prompt.trim()}
              onClick={() => void generate({ prompt: prompt.trim() })}
            >
              Render with this prompt
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => navigator.clipboard?.writeText(prompt)}
            >
              ⧉ Copy prompt
            </button>
          </div>
        </div>
      )}

      {err && <div className="state state-error">⚠ {err}</div>}
    </div>
  )
}
