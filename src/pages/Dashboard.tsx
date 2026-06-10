import { useCallback, useState } from 'react'
import {
  getBacktest,
  getBaselines,
  getContentGaps,
  getDemand,
  getOutliers,
  getPainPoints,
  getPatterns,
  getStatus,
  getTrending,
  minePainPoints,
  minePatterns,
} from '@/services/api'
import type {
  BacktestReport,
  Baseline,
  ContentGap,
  Demand,
  FormatPattern,
  Outlier,
  PainPoint,
  Trending,
} from '@/types'
import { useAsync } from '@/hooks/useAsync'
import { Page, AsyncSection } from '@/components/Page'
import { Bar, Card, Pill, Sparkline, Stat, StatGrid, fmt } from '@/components/ui'

function multTone(m: number): string {
  return m >= 5 ? 'green' : m >= 2 ? 'amber' : 'blue'
}

export default function Dashboard() {
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  const status = useAsync(() => getStatus(), [])
  const backtest = useAsync(() => getBacktest(), [])
  const baselines = useAsync(() => getBaselines(), [])
  const trending = useAsync(() => getTrending(8), [])
  const outliers = useAsync(() => getOutliers(2, 8), [])
  const patterns = useAsync(() => getPatterns(), [tick])
  const pains = useAsync(() => getPainPoints(), [tick])
  const gaps = useAsync(() => getContentGaps(), [tick])

  return (
    <Page
      kicker="Brain intelligence"
      title="Dashboard"
      subtitle="The evidence behind every idea — proven demand, the backtested virality model, mined insights, and live market demand."
    >
      {/* Top stats */}
      <AsyncSection loading={status.loading} error={status.error} data={status.data}>
        {(s) => (
          <StatGrid>
            <Stat label="Channels" value={s.sources} />
            <Stat label="Videos" value={fmt(s.videos)} />
            <Stat label="Transcripts" value={fmt(s.transcripts)} />
            <Stat label="Comments" value={fmt(s.comments)} />
          </StatGrid>
        )}
      </AsyncSection>

      {/* Virality model — the moat */}
      <Card className="moat-card">
        <div className="card-h-row">
          <h3 className="card-h">Virality model</h3>
          <span className="moat-badge">★ The moat</span>
        </div>
        <AsyncSection loading={backtest.loading} error={backtest.error} data={backtest.data}>
          {(bt: BacktestReport) =>
            bt.status !== 'ok' ? (
              <div className="muted">{bt.message || 'Not enough data to backtest yet.'}</div>
            ) : (
              <>
                <p className="muted">
                  Time-split backtest — trained on older videos, tested on newer ({bt.n_train} train ·{' '}
                  {bt.n_test} test). Higher is better.
                </p>
                <StatGrid>
                  <Stat label="ROC-AUC" value={bt.roc_auc ?? '—'} hint="ranking skill (0.5 = chance)" />
                  <Stat
                    label={`Precision@${bt.k}`}
                    value={bt.precision_at_k ?? '—'}
                    hint={`vs ${bt.base_rate} base rate`}
                  />
                  <Stat label="Lift" value={bt.lift_at_k ? `${bt.lift_at_k}×` : '—'} hint="top-k vs random" />
                  <Stat label="Rank corr" value={bt.spearman_corr ?? '—'} hint="score ↔ real multiplier" />
                </StatGrid>
                {bt.top_features && bt.top_features.length > 0 && (
                  <div className="feat-block">
                    <div className="suggest-label">What drives virality on these channels</div>
                    {bt.top_features.map((f) => {
                      const max = Math.max(...bt.top_features!.map((x) => Math.abs(x.weight)))
                      const pct = max > 0 ? (Math.abs(f.weight) / max) * 100 : 0
                      return (
                        <div className="feat-row" key={f.feature}>
                          <span className="feat-name">{f.feature}</span>
                          <div className="bar">
                            <div
                              className="bar-fill"
                              style={{
                                width: `${pct}%`,
                                background: f.weight >= 0 ? '#5ed99a' : '#f08a72',
                              }}
                            />
                          </div>
                          <span className={`feat-w ${f.weight >= 0 ? 'pos' : 'neg'}`}>
                            {f.weight >= 0 ? '+' : ''}
                            {f.weight}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
            )
          }
        </AsyncSection>
      </Card>

      {/* Baselines + Trending */}
      <div className="grid grid-2">
        <Card>
          <h3 className="card-h">Channel baselines</h3>
          <AsyncSection loading={baselines.loading} error={baselines.error} data={baselines.data}>
            {(list: Baseline[]) =>
              list.length === 0 ? (
                <div className="empty">No channels yet.</div>
              ) : (
                <div className="stack">
                  {list.map((b) => (
                    <div className="baseline-row" key={b.channel_id}>
                      <div>
                        <div className="baseline-name">{b.channel_name || b.channel_id}</div>
                        <div className="muted baseline-sub">{b.video_count} videos</div>
                      </div>
                      <div className="baseline-median">
                        {fmt(b.median_views)}
                        <span className="muted baseline-unit"> median views</span>
                      </div>
                    </div>
                  ))}
                </div>
              )
            }
          </AsyncSection>
        </Card>

        <Card>
          <h3 className="card-h">Trending now</h3>
          <p className="muted">Recent videos by velocity (views ÷ days live).</p>
          <AsyncSection loading={trending.loading} error={trending.error} data={trending.data}>
            {(list: Trending[]) =>
              list.length === 0 ? (
                <div className="empty">No recent videos.</div>
              ) : (
                <ul className="rank-list">
                  {list.map((t) => (
                    <li key={t.video_id} className="rank-row">
                      <span className="rank-velocity">{fmt(Math.round(t.velocity))}/day</span>
                      <span className="rank-title">{t.title}</span>
                      <Pill tone={multTone(t.multiplier)}>{t.multiplier}×</Pill>
                    </li>
                  ))}
                </ul>
              )
            }
          </AsyncSection>
        </Card>
      </div>

      {/* Proven demand (outliers) */}
      <Card>
        <h3 className="card-h">Proven demand — top outliers</h3>
        <p className="muted">Videos that beat their channel median the most = validated topics.</p>
        <AsyncSection loading={outliers.loading} error={outliers.error} data={outliers.data}>
          {(list: Outlier[]) =>
            list.length === 0 ? (
              <div className="empty">No outliers yet — scrape a channel.</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Video</th>
                    <th className="num">Views</th>
                    <th className="num">Multiplier</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((o) => (
                    <tr key={o.video_id}>
                      <td className="video-title">{o.title}</td>
                      <td className="num">{fmt(o.views)}</td>
                      <td className="num">
                        <Pill tone={multTone(o.multiplier)}>{o.multiplier}×</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </AsyncSection>
      </Card>

      {/* Mined insights */}
      <div className="grid grid-2">
        <Card>
          <div className="card-h-row">
            <h3 className="card-h">Winning formats</h3>
            <MineButton label="Mine" run={() => minePatterns()} onDone={reload} />
          </div>
          <AsyncSection loading={patterns.loading} error={patterns.error} data={patterns.data}>
            {(list: FormatPattern[]) =>
              list.length === 0 ? (
                <div className="empty">Not mined yet — click Mine (needs Claude).</div>
              ) : (
                <div className="stack">
                  {list.map((p) => (
                    <div key={p.id} className="insight-row">
                      <div className="insight-h">
                        {p.label} <span className="insight-sub">{p.avg_multiplier}× avg</span>
                      </div>
                      <div className="muted">{p.description}</div>
                    </div>
                  ))}
                </div>
              )
            }
          </AsyncSection>
        </Card>

        <Card>
          <div className="card-h-row">
            <h3 className="card-h">Audience pain-points</h3>
            <MineButton label="Mine" run={() => minePainPoints()} onDone={reload} />
          </div>
          <AsyncSection loading={pains.loading} error={pains.error} data={pains.data}>
            {(list: PainPoint[]) =>
              list.length === 0 ? (
                <div className="empty">Not mined yet — click Mine (needs Claude).</div>
              ) : (
                <ul className="suggest-list">
                  {list.map((p) => (
                    <li key={p.id}>
                      <span className="pain-q">{p.question}</span>{' '}
                      <span className="muted">({p.frequency})</span>
                    </li>
                  ))}
                </ul>
              )
            }
          </AsyncSection>
        </Card>
      </div>

      {/* Content gaps */}
      <Card>
        <h3 className="card-h">Content gaps</h3>
        <p className="muted">High-demand pain-points your corpus barely covers = best next videos.</p>
        <AsyncSection loading={gaps.loading} error={gaps.error} data={gaps.data}>
          {(list: ContentGap[]) =>
            list.length === 0 ? (
              <div className="empty">Mine pain-points first.</div>
            ) : (
              <div className="gap-bars">
                {list.slice(0, 8).map((g, i) => (
                  <div className="gap-bar-row" key={i}>
                    <span>{g.covered ? 'covered' : 'GAP'}</span>
                    <Bar value={g.coverage * 100} color={g.covered ? '#5ed99a' : '#e67e22'} />
                    <span className="gap-q">{g.question}</span>
                  </div>
                ))}
              </div>
            )
          }
        </AsyncSection>
      </Card>

      {/* Demand explorer */}
      <DemandExplorer />
    </Page>
  )
}

function MineButton({ label, run, onDone }: { label: string; run: () => Promise<unknown>; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const go = async () => {
    setBusy(true)
    setErr(null)
    try {
      await run()
      onDone()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed')
    } finally {
      setBusy(false)
    }
  }
  return (
    <span className="mine-wrap">
      <button className="btn btn-ghost mine-btn" onClick={go} disabled={busy}>
        {busy ? 'Mining…' : label}
      </button>
      {err && <span className="mine-err">⚠ {err}</span>}
    </span>
  )
}

function DemandExplorer() {
  const [kw, setKw] = useState('')
  const [data, setData] = useState<Demand | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const go = async () => {
    if (!kw.trim()) return
    setBusy(true)
    setErr(null)
    try {
      setData(await getDemand(kw.trim()))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h3 className="card-h">Market demand</h3>
      <p className="muted">Google Trends direction + YouTube autocomplete for any keyword.</p>
      <div className="add-src">
        <input
          className="input"
          placeholder="e.g. cold email"
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && go()}
        />
        <button className="btn" onClick={go} disabled={busy}>
          {busy ? 'Checking…' : 'Check demand'}
        </button>
      </div>
      {err && <div className="state state-error">⚠ {err}</div>}
      {data && (
        <div className="demand-result">
          <div className="demand-row">
            {data.trends.available ? (
              <>
                <div>
                  <span className="demand-interest">{data.trends.interest}</span>
                  <span className="demand-interest-unit">/100 interest</span>
                  <Pill
                    tone={
                      data.trends.direction === 'rising'
                        ? 'green'
                        : data.trends.direction === 'falling'
                          ? 'red'
                          : 'blue'
                    }
                  >
                    {data.trends.direction}
                  </Pill>
                </div>
                {data.trends.history && (
                  <Sparkline points={data.trends.history} color="#e67e22" />
                )}
              </>
            ) : (
              <span className="muted">Trends unavailable ({data.trends.reason || 'rate-limited'}).</span>
            )}
          </div>
          {data.suggestions.length > 0 && (
            <>
              <div className="suggest-label">People also search</div>
              <div className="chips">
                {data.suggestions.map((s) => (
                  <Pill key={s} tone="default">
                    {s}
                  </Pill>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}
