'use client';

import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Button } from '@/components/ui/button';
import { categories, summarizeExtent, type ExtentRow } from '@/lib/extent';

const showNames: Record<string, string> = { jre: 'Joe Rogan Experience', doac: 'Diary of a CEO' };
const config = {
  present: { label: 'Present', color: '#cb7569' },
  advanced: { label: 'Asserted / tentative', color: '#347b70' },
};

export function ExtentOverview({ rows, onEpisode, onWindow }: {
  rows: ExtentRow[];
  onEpisode: (row: { show: string; episodeId: string }) => void;
  onWindow: (id: string) => void;
}) {
  const [denominator, setDenominator] = useState<'all' | 'screened'>('all');
  const summary = useMemo(() => summarizeExtent(rows), [rows]);
  const denom = (group: { windows: number; screened: number }) => denominator === 'all' ? group.windows : group.screened;
  const pct = (count: number, n: number) => n ? 100 * count / n : 0;
  const chart = summary.shows.filter(show => denom(show) > 0).map(show => ({
    name: showNames[show.show] ?? show.show,
    present: Number(pct(show.present, denom(show)).toFixed(1)),
    advanced: Number(pct(show.advanced, denom(show)).toFixed(1)),
  }));
  if (!rows.length) return <div className="empty-state"><strong>No windows in this selection</strong><span>Broaden a filter to see the comparison.</span></div>;
  return <div className="extent-overview">
    <div className="extent-heading">
      <div><span className="eyebrow">Explore the extent</span><h2>Where do the flags appear?</h2>
        <p>All charts follow your filters. Percentages use {denominator === 'all' ? 'all selected windows' : 'selected health/science-positive windows'}.</p></div>
      <div className="view-toggle" aria-label="Percentage denominator">
        <Button variant={denominator === 'all' ? 'default' : 'ghost'} onClick={() => setDenominator('all')}>All windows</Button>
        <Button variant={denominator === 'screened' ? 'default' : 'ghost'} onClick={() => setDenominator('screened')}>Health / science only</Button>
      </div>
    </div>
    <div className="extent-grid">
      <section className="extent-panel">
        <h3>Presence and advancement</h3>
        <p>Presence includes reporting and rejection. Advancement counts asserted or tentative claims.</p>
        {chart.length ? <ChartContainer config={config} className="extent-chart">
          <BarChart data={chart} layout="vertical" margin={{ left: 0, right: 20, top: 10, bottom: 5 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" domain={[0, 100]} tickFormatter={value => `${value}%`} />
            <YAxis dataKey="name" type="category" width={105} tick={{ fontSize: 10 }} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="present" fill="var(--color-present)" radius={[0, 4, 4, 0]} maxBarSize={28} />
            <Bar dataKey="advanced" fill="var(--color-advanced)" radius={[0, 4, 4, 0]} maxBarSize={28} />
          </BarChart>
        </ChartContainer> : <p>No health/science-positive windows in this selection.</p>}
        <div className="extent-key"><span><i style={{ background: '#cb7569' }} /> Present</span><span><i style={{ background: '#347b70' }} /> Asserted / tentative</span></div>
        <div className="show-counts">{summary.shows.map(show => <p key={show.show}><strong>{showNames[show.show]}</strong><br />{show.present} present · {show.advanced} advanced · {show.uncertain} uncertain · denominator {denom(show)}</p>)}</div>
      </section>
      <section className="extent-panel">
        <h3>What contributes to broad fringe?</h3><p>Categories overlap. Each window counts once per category; unmatched quotations are excluded.</p>
        <div className="category-comparison">{Object.entries(categories).map(([key, label]) => <div key={key}>
          <h4>{label}</h4>{summary.shows.map(show => <div className="category-bar-row" key={show.show}>
            <span>{show.show.toUpperCase()}</span><div className="category-track"><i style={{ width: `${pct(show.categories[key], denom(show))}%`, background: show.show === 'jre' ? '#347b70' : '#a97645' }} /></div>
            <strong>{denom(show) ? `${pct(show.categories[key], denom(show)).toFixed(1)}%` : '—'}</strong>
          </div>)}
        </div>)}</div>
      </section>
    </div>
    <section className="episode-ranking">
      <h3>Episode comparison</h3><p>Click an episode to inspect its windows. Bars show broad fringe presence on a 0–100% scale.</p>
      {summary.episodes.map(episode => <button key={`${episode.show}:${episode.episodeId}`} onClick={() => onEpisode(episode)} className="episode-rank-row">
        <span className="rank-episode"><small>{episode.show.toUpperCase()}</small><strong>{episode.guest || episode.title}</strong></span>
        <span className="rank-track"><i style={{ width: `${pct(episode.present, denom(episode))}%` }} /></span>
        <span className="rank-number">{denom(episode) ? `${pct(episode.present, denom(episode)).toFixed(1)}%` : '—'}<small>{episode.present} / {denom(episode)} windows</small></span>
      </button>)}
    </section>
    {summary.episodes.length === 1 && <section className="extent-panel window-map">
      <h3>Transcript sequence</h3><p>Each tile is one selected window, ordered by window number. Click to read it. Adjacent windows overlap.</p>
      <div>{[...rows].sort((a, b) => a.windowId - b.windowId).map(row => <button className={`bar-${row.status}`} key={row.id} title={`Window ${row.windowId}: ${row.status.replaceAll('_', ' ')}`} aria-label={`Inspect window ${row.windowId}: ${row.status.replaceAll('_', ' ')}`} onClick={() => onWindow(row.id)}>{row.windowId}</button>)}</div>
    </section>}
    <p className="extent-caveat">These are provisional model judgments about overlapping text windows, not percentages of airtime, unique claims, or misinformation. Emerging research and exaggeration can trigger a broad flag. Uncertainty is retained separately.</p>
  </div>;
}
