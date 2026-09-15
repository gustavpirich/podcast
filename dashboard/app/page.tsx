'use client';

import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Download,
  FlaskConical,
  HeartPulse,
  List,
  PackageSearch,
  RotateCcw,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ReviewWorkspace } from '@/components/review-workspace';
import { ExtentOverview } from '@/components/extent-overview';
import { ProductOverview } from '@/components/product-overview';

type FringeStatus = 'fringe' | 'uncertain' | 'not_fringe' | 'not_assessable' | 'not_screened';
type Claim = {
  id: string;
  text: string;
  modelText: string;
  domain: string;
  type: string;
  consensus: string;
  exaggeration: string;
  advancedStatus: string;
  status: FringeStatus;
  modelStatus: FringeStatus;
  reason: string;
  matchMethod: string;
  textMatched: boolean;
  codingConsistent: boolean;
  statementUnitId: string;
  unitInstanceCount: number;
  isRepresentative: boolean;
  primaryObject: string;
  secondaryObjects: string[];
  claimFocus: string;
  productMaturity: string;
  extractionQuality: string;
  objectReason: string;
  objectResponseId: string;
};
type WindowRecord = {
  id: string;
  show: string;
  episodeId: string;
  episodeTitle: string;
  guest: string;
  publishedDate: string;
  advancedStatus: FringeStatus;
  windowId: number;
  wordStart: number;
  wordEnd: number;
  startMs: number;
  endMs: number;
  speakers: string[];
  screenHealth: boolean;
  screenScience: boolean;
  health: boolean;
  science: boolean;
  stage05Requested: boolean;
  status: FringeStatus;
  claimCount: number;
  fringeClaimCount: number;
  uncertainClaimCount: number;
  notFringeClaimCount: number;
  codingInconsistencies: number;
  nonExactClaims: number;
  unmatchedClaims: number;
  stage04HealthRationale: string;
  stage04ScienceRationale: string;
  snippet: string;
  claims: Claim[];
  needsHumanReview: boolean;
  humanDecision: string;
};
type DashboardData = {
  meta: {
    generatedAt: string;
    source: string;
    sourceSha256: string;
    status: string;
    unit: string;
    definition: string;
    statementDefinition: string;
    statementSource: string;
    statementSourceSha256: string;
  };
  summary: {
    shows: number;
    episodes: number;
    windows: number;
    stage05Requested: number;
    healthWindows: number;
    scienceWindows: number;
    claims: number;
    statementUnits: number;
    repeatedClaimInstances: number;
    statuses: Record<FringeStatus, number>;
  };
  episodes: Array<{
    show: string;
    episodeId: string;
    title: string;
    windows: number;
    healthWindows: number;
    scienceWindows: number;
    claims: number;
    statuses: Record<FringeStatus, number>;
  }>;
  windows: WindowRecord[];
};

const PAGE_SIZE = 30;
const objectLabels: Record<string, string> = {
  vaccines_immunization: 'Vaccines & immunization',
  pharmaceuticals_biologics: 'Pharmaceuticals & biologics',
  peptides_hormones: 'Peptides & hormones',
  supplements_nutraceuticals: 'Supplements & nutraceuticals',
  psychoactive_substances: 'Psychoactive substances',
  medical_procedures_devices: 'Medical procedures & devices',
  diet_nutrition: 'Diet & nutrition',
  exercise_physical_activity: 'Exercise & physical activity',
  sleep_recovery: 'Sleep & recovery',
  mental_behavioral_interventions: 'Mental & behavioral interventions',
  environmental_lifestyle_exposures: 'Environmental & lifestyle exposures',
  healthcare_public_health: 'Healthcare & public health',
  disease_condition: 'Disease or condition',
  non_health_science: 'Non-health science',
  other_health: 'Other health',
  unclear: 'Unclear',
};
const statusLabels: Record<FringeStatus, string> = {
  fringe: 'Broad fringe',
  uncertain: 'Uncertain',
  not_fringe: 'Not fringe',
  not_assessable: 'Not assessable',
  not_screened: 'Screen negative',
};
const statusClasses: Record<FringeStatus, string> = {
  fringe: 'status-fringe',
  uncertain: 'status-uncertain',
  not_fringe: 'status-supported',
  not_assessable: 'status-neutral',
  not_screened: 'status-neutral',
};

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000),
    hours = Math.floor(seconds / 3600),
    minutes = Math.floor((seconds % 3600) / 60),
    remainder = seconds % 60;
  return `${hours ? `${hours}:` : ''}${String(minutes).padStart(hours ? 2 : 1, '0')}:${String(remainder).padStart(2, '0')}`;
}
function StatusBadge({ status }: { status: FringeStatus }) {
  return (
    <Badge className={statusClasses[status]}>{statusLabels[status]}</Badge>
  );
}
function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <div className="metric-card">
      <p>{label}</p>
      <strong>{value.toLocaleString()}</strong>
      <span>{detail}</span>
    </div>
  );
}

function csvCell(value: string | number | boolean) {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export default function Home() {
  const [data, setData] = useState<DashboardData | null>(null),
    [error, setError] = useState(''),
    [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const [show, setShow] = useState('all'),
    [episode, setEpisode] = useState('all'),
    [status, setStatus] = useState('all'),
    [content, setContent] = useState('all');
  const [issuesOnly, setIssuesOnly] = useState(false),
    [positionFilter, setPositionFilter] = useState('all'),
    [exaggerationFilter, setExaggerationFilter] = useState('all'),
    [stanceFilter, setStanceFilter] = useState('all'),
    [objectFilter, setObjectFilter] = useState('all'),
    [focusFilter, setFocusFilter] = useState('all'),
    [maturityFilter, setMaturityFilter] = useState('all'),
    [qualityFilter, setQualityFilter] = useState('all'),
    [page, setPage] = useState(1),
    [selected, setSelected] = useState<WindowRecord | null>(null),
    [view, setView] = useState<'windows' | 'episodes' | 'review' | 'overview' | 'products'>('products');

  useEffect(() => {
    fetch('/data/classifications.json')
      .then((response) => {
        if (!response.ok)
          throw new Error(`Dataset request failed (${response.status})`);
        return response.json();
      })
      .then((payload) => {
        const result = payload as DashboardData;
        if (result?.meta?.definition !== 'broad_fringe_science_v1' || result?.meta?.statementDefinition !== 'health_object_focus_v1' || !Array.isArray(result.windows))
          throw new Error('Please refresh the dashboard data from the completed product classification.');
        setData(result);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);
  const episodes = useMemo(
    () =>
      (data?.episodes ?? []).filter(
        (item) => show === 'all' || item.show === show,
      ),
    [data, show],
  );
  const filtered = useMemo(() => {
    if (!data) return [];
    return data.windows.filter((row) => {
      if (show !== 'all' && row.show !== show) return false;
      if (episode !== 'all' && row.episodeId !== episode) return false;
      if (status !== 'all' && row.status !== status) return false;
      if (content === 'health' && !row.health) return false;
      if (content === 'science' && !row.science) return false;
      if (content === 'both' && !(row.health && row.science)) return false;
      if (content === 'neither' && (row.health || row.science)) return false;
      if (issuesOnly && !row.codingInconsistencies && !row.unmatchedClaims)
        return false;
      if ((positionFilter !== 'all' || exaggerationFilter !== 'all' || stanceFilter !== 'all' || objectFilter !== 'all' || focusFilter !== 'all' || maturityFilter !== 'all' || qualityFilter !== 'all') &&
        !row.claims.some(claim =>
          (positionFilter === 'all' || claim.consensus === positionFilter) &&
          (exaggerationFilter === 'all' || claim.exaggeration === exaggerationFilter) &&
          (stanceFilter === 'all' || claim.type === stanceFilter) &&
          (objectFilter === 'all' || claim.primaryObject === objectFilter || claim.secondaryObjects.includes(objectFilter)) &&
          (focusFilter === 'all' || claim.claimFocus === focusFilter) &&
          (maturityFilter === 'all' || claim.productMaturity === maturityFilter) &&
          (qualityFilter === 'all' || claim.extractionQuality === qualityFilter))) return false;
      if (deferredQuery) {
        const haystack = [
          row.episodeTitle,
          row.episodeId,
          row.snippet,
          row.speakers.join(' '),
          row.guest,
          ...row.claims.map((claim) => `${claim.text} ${claim.reason} ${claim.objectReason} ${claim.primaryObject}`),
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(deferredQuery)) return false;
      }
      return true;
    });
  }, [data, show, episode, status, content, issuesOnly, deferredQuery, positionFilter, exaggerationFilter, stanceFilter, objectFilter, focusFilter, maturityFilter, qualityFilter]);
  useEffect(
    () => setPage(1),
    [show, episode, status, content, issuesOnly, deferredQuery, positionFilter, exaggerationFilter, stanceFilter, objectFilter, focusFilter, maturityFilter, qualityFilter],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)),
    visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const filteredStatements = useMemo(() => filtered.flatMap((window) =>
    window.claims.filter((claim) =>
      claim.isRepresentative &&
      (status === 'all' || claim.status === status) &&
      (positionFilter === 'all' || claim.consensus === positionFilter) &&
      (exaggerationFilter === 'all' || claim.exaggeration === exaggerationFilter) &&
      (stanceFilter === 'all' || claim.type === stanceFilter) &&
      (objectFilter === 'all' || claim.primaryObject === objectFilter || claim.secondaryObjects.includes(objectFilter)) &&
      (focusFilter === 'all' || claim.claimFocus === focusFilter) &&
      (maturityFilter === 'all' || claim.productMaturity === maturityFilter) &&
      (qualityFilter === 'all' || claim.extractionQuality === qualityFilter)
    ).map((claim) => ({ window, claim }))),
    [filtered, status, positionFilter, exaggerationFilter, stanceFilter, objectFilter, focusFilter, maturityFilter, qualityFilter]);
  const filteredStats = useMemo(() => {
    const statuses = {
      fringe: 0,
      uncertain: 0,
      not_fringe: 0,
      not_assessable: 0,
      not_screened: 0,
    } as Record<FringeStatus, number>;
    let claims = 0;
    let health = 0;
    let science = 0;
    for (const row of filtered) {
      statuses[row.status] += 1;
      claims += row.claimCount;
      health += Number(row.health);
      science += Number(row.science);
    }
    return { statuses, claims, health, science };
  }, [filtered]);
  const episodeSummary = useMemo(() => {
    const grouped = new Map<
      string,
      {
        show: string;
        episodeId: string;
        title: string;
        windows: number;
        health: number;
        science: number;
        claims: number;
        statuses: Record<FringeStatus, number>;
      }
    >();
    for (const row of filtered) {
      const key = `${row.show}:${row.episodeId}`;
      const current = grouped.get(key) ?? {
        show: row.show,
        episodeId: row.episodeId,
        title: row.episodeTitle,
        windows: 0,
        health: 0,
        science: 0,
        claims: 0,
        statuses: { fringe: 0, uncertain: 0, not_fringe: 0, not_assessable: 0, not_screened: 0 },
      };
      current.windows += 1;
      current.health += Number(row.health);
      current.science += Number(row.science);
      current.claims += row.claimCount;
      current.statuses[row.status] += 1;
      grouped.set(key, current);
    }
    return [...grouped.values()].sort(
      (a, b) =>
        b.statuses.fringe - a.statuses.fringe || a.title.localeCompare(b.title),
    );
  }, [filtered]);

  function resetFilters() {
    setQuery('');
    setShow('all');
    setEpisode('all');
    setStatus('all');
    setContent('all');
    setIssuesOnly(false);
    setPositionFilter('all');
    setExaggerationFilter('all');
    setStanceFilter('all');
    setObjectFilter('all');
    setFocusFilter('all');
    setMaturityFilter('all');
    setQualityFilter('all');
  }

  function downloadFiltered() {
    const headers = [
      'show',
      'episode_id',
      'episode_title',
      'window_id',
      'start_time',
      'health_related',
      'science_related',
      'broad_status',
      'advanced_status',
      'snippet_id',
      'source_sha256',
      'claim_count',
      'claim_texts',
      'snippet_text',
      'claims_json',
    ];
    const lines = [headers.join(',')];
    for (const row of filtered) {
      lines.push(
        [
          row.show,
          row.episodeId,
          row.episodeTitle,
          row.windowId,
          formatTime(row.startMs),
          row.health,
          row.science,
          row.status,
          row.advancedStatus,
          row.id,
          data?.meta.sourceSha256 ?? '',
          row.claimCount,
          row.claims.map((claim) => claim.text || claim.modelText).join(' || '),
          row.snippet,
          JSON.stringify(row.claims),
        ]
          .map(csvCell)
          .join(','),
      );
    }
    const blob = new Blob([lines.join('\n')], {
      type: 'text/csv;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `classification-windows-${filtered.length}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (error)
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="max-w-md rounded-2xl border bg-card p-6 shadow-sm">
          <AlertTriangle className="mb-4 text-red-600" />
          <h1 className="text-xl font-semibold">
            The classification data could not be loaded
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        </div>
      </main>
    );

  return (
    <main className="min-h-screen">
      <header className="topbar">
        <div>
          <div className="eyebrow">Podcast observational study · Broad classification</div>
          <h1>Classification inspector</h1>
        </div>
        <div className="provisional-note">
          <span className="pulse-dot" /> Provisional model labels · human review
          required
        </div>
      </header>
      <div className="dashboard-shell">
        <section className="summary-grid" aria-label="Corpus summary">
          <Metric
            label="Transcript windows"
            value={data?.summary.windows ?? 0}
            detail="256 words · 128 stride"
          />
          <Metric
            label="Episodes"
            value={data?.summary.episodes ?? 0}
            detail={`${data?.summary.shows ?? 0} podcast series`}
          />
          <Metric
            label="Unique statements"
            value={data?.summary.statementUnits ?? 0}
            detail={`${(data?.summary.claims ?? 0).toLocaleString()} overlapping instances`}
          />
          <Metric
            label="Broad fringe present"
            value={data?.summary.statuses.fringe ?? 0}
            detail="Non-mainstream or exaggerated"
          />
        </section>
        <section
          className="distribution-card"
          aria-label="Filtered classification distribution"
        >
          <div className="distribution-copy">
            <div>
              <span className="eyebrow">Current selection</span>
              <strong>
                {filtered.length.toLocaleString()} windows ·{' '}
                {filteredStats.claims.toLocaleString()} claims
              </strong>
            </div>
            <p>
              {filteredStats.health.toLocaleString()} health ·{' '}
              {filteredStats.science.toLocaleString()} science
            </p>
          </div>
          <div
            className="distribution-bar"
            aria-label="Fringe status distribution"
          >
            {(Object.keys(statusLabels) as FringeStatus[]).map((item) => {
              const count = filteredStats.statuses[item];
              return count > 0 ? (
                <button
                  key={item}
                  className={`bar-${item}`}
                  style={{
                    width: `${(count / Math.max(filtered.length, 1)) * 100}%`,
                  }}
                  title={`${statusLabels[item]}: ${count.toLocaleString()}`}
                  onClick={() => setStatus(item)}
                >
                  <span>{count.toLocaleString()}</span>
                </button>
              ) : null;
            })}
          </div>
          <div className="distribution-legend">
            {(Object.keys(statusLabels) as FringeStatus[]).map((item) => (
              <button
                key={item}
                onClick={() => setStatus(status === item ? 'all' : item)}
                data-active={status === item}
              >
                <i className={`legend-${item}`} /> {statusLabels[item]}{' '}
                <strong>{filteredStats.statuses[item].toLocaleString()}</strong>
              </button>
            ))}
          </div>
        </section>
        <section className="workspace-card">
          <div className="filter-panel">
            <div className="filter-heading filter-heading-row">
              <SlidersHorizontal />
              <div>
                <h2>Explore classifications</h2>
                <p>
                  {data
                    ? `${filtered.length.toLocaleString()} of ${data.summary.windows.toLocaleString()} windows`
                    : 'Loading classification data…'}
                </p>
              </div>
              <div className="view-actions">
                <div className="view-toggle" aria-label="Choose result view">
                  <Button size="sm" variant={view === 'products' ? 'default' : 'ghost'} onClick={() => setView('products')}>
                    <PackageSearch /> Products
                  </Button>
                  <Button size="sm" variant={view === 'overview' ? 'default' : 'ghost'} onClick={() => setView('overview')}>
                    <BarChart3 /> Overview
                  </Button>
                  <Button
                    size="sm"
                    variant={view === 'windows' ? 'default' : 'ghost'}
                    onClick={() => setView('windows')}
                  >
                    <List /> Windows
                  </Button>
                  <Button
                    size="sm"
                    variant={view === 'episodes' ? 'default' : 'ghost'}
                    onClick={() => setView('episodes')}
                  >
                    <BarChart3 /> Episodes
                  </Button>
                  <Button
                    size="sm"
                    variant={view === 'review' ? 'default' : 'ghost'}
                    onClick={() => setView('review')}
                  >
                    <ClipboardCheck /> Review
                  </Button>
                </div>
                <Button size="sm" variant="outline" onClick={resetFilters}>
                  <RotateCcw /> Reset
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!filtered.length}
                  onClick={downloadFiltered}
                >
                  <Download /> Export
                </Button>
              </div>
            </div>
            <div className="search-wrap">
              <Search aria-hidden="true" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search transcript, claim, speaker, or episode…"
                aria-label="Search transcript windows"
              />
            </div>
            <div className="filter-row">
              <Select
                value={show}
                onValueChange={(value) => { setShow(value ?? 'all'); setEpisode('all'); }}
              >
                <SelectTrigger aria-label="Filter by show">
                  <SelectValue placeholder="All shows" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All shows</SelectItem>
                  <SelectItem value="doac">Diary of a CEO</SelectItem>
                  <SelectItem value="jre">Joe Rogan Experience</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={episode}
                onValueChange={(value) => setEpisode(value ?? 'all')}
              >
                <SelectTrigger
                  className="episode-trigger"
                  aria-label="Filter by episode"
                >
                  <SelectValue placeholder="All episodes" />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectItem value="all">All episodes</SelectItem>
                  {episodes.map((item) => (
                    <SelectItem
                      key={`${item.show}-${item.episodeId}`}
                      value={item.episodeId}
                    >
                      {item.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={status}
                onValueChange={(value) => setStatus(value ?? 'all')}
              >
                <SelectTrigger aria-label="Filter by fringe status">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="fringe">Broad fringe</SelectItem>
                  <SelectItem value="uncertain">Uncertain</SelectItem>
                  <SelectItem value="not_fringe">Not fringe</SelectItem>
                  <SelectItem value="not_assessable">Not assessable</SelectItem>
                  <SelectItem value="not_screened">Screen negative</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={content}
                onValueChange={(value) => setContent(value ?? 'all')}
              >
                <SelectTrigger aria-label="Filter by content domain">
                  <SelectValue placeholder="All content" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All content</SelectItem>
                  <SelectItem value="health">Health</SelectItem>
                  <SelectItem value="science">Science</SelectItem>
                  <SelectItem value="both">Health + science</SelectItem>
                  <SelectItem value="neither">Neither</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant={issuesOnly ? 'default' : 'outline'}
                onClick={() => setIssuesOnly((value) => !value)}
              >
                <AlertTriangle /> Review flags
              </Button>
            </div>
            <div className="filter-row claim-filters">
              <Select value={objectFilter} onValueChange={value => setObjectFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by health product or behavior"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">All products & behaviors</SelectItem>{Object.entries(objectLabels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={focusFilter} onValueChange={value => setFocusFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by claim focus"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">All claim focuses</SelectItem>{['efficacy_benefit','risk_safety','mechanism','use_dose_access','recommendation','regulation_policy','prevalence_adoption','diagnosis_detection','general_description','other','unclear'].map(value => <SelectItem key={value} value={value}>{value.replaceAll('_', ' ')}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={maturityFilter} onValueChange={value => setMaturityFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by product maturity"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">Any product maturity</SelectItem>{['established_marketed','new_or_emerging','investigational_experimental','off_label_or_repurposed','unregulated_or_nonmedical','not_applicable','uncertain'].map(value => <SelectItem key={value} value={value}>{value.replaceAll('_', ' ')}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={qualityFilter} onValueChange={value => setQualityFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by extraction quality"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">Any extraction quality</SelectItem>{['atomic_checkable','compound_checkable','not_checkable','unclear_fragment'].map(value => <SelectItem key={value} value={value}>{value.replaceAll('_', ' ')}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="filter-row claim-filters">
              <Select value={positionFilter} onValueChange={value => setPositionFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by scientific position"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All scientific positions</SelectItem>
                  <SelectItem value="mainstream">Mainstream</SelectItem>
                  <SelectItem value="emerging_non_mainstream">Emerging non-mainstream</SelectItem>
                  <SelectItem value="alternative_speculative">Alternative / speculative</SelectItem>
                  <SelectItem value="contradicts_consensus">Contradicts consensus</SelectItem>
                  <SelectItem value="uncertain">Position uncertain</SelectItem>
                </SelectContent>
              </Select>
              <Select value={exaggerationFilter} onValueChange={value => setExaggerationFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by exaggeration"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Any exaggeration label</SelectItem>
                  <SelectItem value="yes">Exaggeration: yes</SelectItem>
                  <SelectItem value="no">Exaggeration: no</SelectItem>
                  <SelectItem value="uncertain">Exaggeration: uncertain</SelectItem>
                </SelectContent>
              </Select>
              <Select value={stanceFilter} onValueChange={value => setStanceFilter(value ?? 'all')}>
                <SelectTrigger aria-label="Filter by claim stance"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All claim stances</SelectItem>
                  {['asserted', 'tentative', 'reported', 'rejected', 'unclear'].map(value => <SelectItem key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</SelectItem>)}
                </SelectContent>
              </Select>
              <span className="filter-help">These filters must match the same claim. Results retain its full window.</span>
            </div>
          </div>
          {view === 'products' ? (
            <ProductOverview statements={filteredStatements} totalUnits={data?.summary.statementUnits ?? 0} repeatedInstances={data?.summary.repeatedClaimInstances ?? 0} onObject={value => setObjectFilter(value)} onSelect={id => setSelected(data?.windows.find(row => row.id === id) ?? null)} />
          ) : view === 'overview' ? (
            <ExtentOverview rows={filtered} onEpisode={(item) => { setShow(item.show); setEpisode(item.episodeId); setView('windows'); }} onWindow={id => setSelected(filtered.find(row => row.id === id) ?? null)} />
          ) : view === 'windows' ? (
            <>
              <div className="table-wrap" aria-busy={!data}>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Status</TableHead>
                      <TableHead>Episode</TableHead>
                      <TableHead>Window</TableHead>
                      <TableHead>Domain</TableHead>
                      <TableHead>Claims</TableHead>
                      <TableHead className="w-[45%]">
                        Transcript excerpt
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {!data &&
                      Array.from({ length: 8 }).map((_, index) => (
                        <TableRow key={index}>
                          <TableCell colSpan={6}>
                            <div className="loading-line" />
                          </TableCell>
                        </TableRow>
                      ))}
                    {data &&
                      visible.map((row) => (
                        <TableRow
                          key={row.id}
                          className="cursor-pointer"
                          tabIndex={0}
                          onClick={() => setSelected(row)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ')
                              setSelected(row);
                          }}
                        >
                          <TableCell>
                            <StatusBadge status={row.status} />
                          </TableCell>
                          <TableCell>
                            <div className="episode-cell">
                              <span>{row.show.toUpperCase()}</span>
                              <strong>{row.episodeTitle}</strong>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="window-cell">
                              <strong>#{row.windowId}</strong>
                              <span>{formatTime(row.startMs)}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="domain-icons">
                              {row.health && (
                                <span title="Health related">
                                  <HeartPulse /> Health
                                </span>
                              )}
                              {row.science && (
                                <span title="Science related">
                                  <FlaskConical /> Science
                                </span>
                              )}
                              {!row.health && !row.science && (
                                <span className="muted-domain">—</span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <strong>{row.claimCount}</strong>
                          </TableCell>
                          <TableCell>
                            <p className="excerpt">{row.snippet}</p>
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
                {data && !visible.length && (
                  <div className="empty-state">
                    <Search />
                    <strong>No windows match these filters</strong>
                    <span>Clear or broaden a filter to continue.</span>
                  </div>
                )}
              </div>
              <footer className="pagination-bar">
                <span>
                  {filtered.length
                    ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, filtered.length)} of ${filtered.length.toLocaleString()}`
                    : '0 results'}
                </span>
                <div>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label="Previous page"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => value - 1)}
                  >
                    <ChevronLeft />
                  </Button>
                  <span>
                    Page {page} of {pages}
                  </span>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label="Next page"
                    disabled={page >= pages}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    <ChevronRight />
                  </Button>
                </div>
              </footer>
            </>
          ) : view === 'episodes' ? (
            <div className="table-wrap episode-overview" aria-busy={!data}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Episode</TableHead>
                    <TableHead>Windows</TableHead>
                    <TableHead>Health</TableHead>
                    <TableHead>Science</TableHead>
                    <TableHead>Claims</TableHead>
                    <TableHead className="w-[34%]">
                      Window status distribution
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {episodeSummary.map((item) => (
                    <TableRow
                      key={`${item.show}-${item.episodeId}`}
                      tabIndex={0}
                      onClick={() => {
                        setShow(item.show);
                        setEpisode(item.episodeId);
                        setView('windows');
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          setShow(item.show);
                          setEpisode(item.episodeId);
                          setView('windows');
                        }
                      }}
                    >
                      <TableCell>
                        <div className="episode-cell episode-overview-title">
                          <span>{item.show.toUpperCase()}</span>
                          <strong>{item.title}</strong>
                        </div>
                      </TableCell>
                      <TableCell>{item.windows.toLocaleString()}</TableCell>
                      <TableCell>{item.health.toLocaleString()}</TableCell>
                      <TableCell>{item.science.toLocaleString()}</TableCell>
                      <TableCell>{item.claims.toLocaleString()}</TableCell>
                      <TableCell>
                        <div
                          className="mini-bar"
                          aria-label={`Status distribution for ${item.title}`}
                        >
                          {(Object.keys(statusLabels) as FringeStatus[]).map(
                            (state) =>
                              item.statuses[state] ? (
                                <i
                                  key={state}
                                  className={`bar-${state}`}
                                  style={{
                                    width: `${(item.statuses[state] / item.windows) * 100}%`,
                                  }}
                                  title={`${statusLabels[state]}: ${item.statuses[state]}`}
                                />
                              ) : null,
                          )}
                        </div>
                        <div className="mini-labels">
                          <span>{item.statuses.fringe} fringe</span>
                          <span>{item.statuses.uncertain} uncertain</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {data && !episodeSummary.length && (
                <div className="empty-state">
                  <BarChart3 />
                  <strong>No episodes match these filters</strong>
                  <span>Clear or broaden a filter to continue.</span>
                </div>
              )}
            </div>
          ) : (
            <ReviewWorkspace key={data?.meta.sourceSha256 ?? 'loading'} rows={filtered} sourceHash={data?.meta.sourceSha256 ?? ''} positionFilter={positionFilter} exaggerationFilter={exaggerationFilter} stanceFilter={stanceFilter} />
          )}
        </section>
        <footer className="method-footer">
          <div>
            <strong>Reading the data</strong>
            <p>
              Every row is one complete 256-word transcript window. Adjacent
              windows overlap by 128 words, so claim totals can repeat the same
              spoken claim. Fringe labels are provisional model assessments.
              Broad fringe includes emerging non-mainstream, alternative/speculative,
              consensus-contradicting, or exaggerated claims. It does not imply
              misinformation. Uncertain remains separate. Screen negatives did not
              receive claim classification; they are not confirmed non-fringe.
            </p>
          </div>
          <dl>
            <div>
              <dt>Source</dt>
              <dd>{data?.meta.source ?? 'Loading…'}</dd>
            </div>
            <div>
              <dt>Dataset hash</dt>
              <dd>{data?.meta.sourceSha256.slice(0, 16) ?? '—'}…</dd>
            </div>
            <div>
              <dt>Generated</dt>
              <dd>
                {data ? new Date(data.meta.generatedAt).toLocaleString() : '—'}
              </dd>
            </div>
          </dl>
        </footer>
      </div>
      <Dialog
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="detail-dialog">
          {selected && (
            <>
              <DialogHeader className="detail-header">
                <div className="flex items-center gap-2">
                  <StatusBadge status={selected.status} />
                  <span>
                    {selected.show.toUpperCase()} · window {selected.windowId}
                  </span>
                </div>
                <DialogTitle>{selected.episodeTitle}</DialogTitle>
                <DialogDescription>
                  {formatTime(selected.startMs)}–{formatTime(selected.endMs)} ·{' '}
                  Guest: {selected.guest} · {selected.publishedDate}
                </DialogDescription>
              </DialogHeader>
              <div className="detail-scroll">
                <section
                  className="window-facts"
                  aria-label="Window classification facts"
                >
                  <div>
                    <span>Word range</span>
                    <strong>
                      {selected.wordStart}–{selected.wordEnd - 1}
                    </strong>
                  </div>
                  <div>
                    <span>Health</span>
                    <strong>{selected.health ? 'Yes' : 'No'}</strong>
                  </div>
                  <div>
                    <span>Science</span>
                    <strong>{selected.science ? 'Yes' : 'No'}</strong>
                  </div>
                  <div>
                    <span>Claim classification</span>
                    <strong>
                      {selected.stage05Requested
                        ? 'Completed'
                        : 'Screen negative'}
                    </strong>
                  </div>
                </section>
                {(selected.codingInconsistencies > 0 ||
                  selected.unmatchedClaims > 0) && (
                  <section className="review-alert">
                    <AlertTriangle />
                    <div>
                      <strong>Review flags present</strong>
                      <p>
                        {selected.unmatchedClaims} unmatched quotations retained as uncertain.
                      </p>
                    </div>
                  </section>
                )}
                <section className="detail-section">
                  <h3>Transcript window</h3>
                  <p className="transcript-copy">{selected.snippet}</p>
                </section>
                <section className="detail-section">
                  <h3>Presence versus advancement</h3>
                  <p>Present: {statusLabels[selected.status]}. Asserted or tentatively advanced: {statusLabels[selected.advancedStatus]}.</p>
                  <p>Reported and rejected claims can contribute to presence without contributing to advancement.</p>
                </section>
                <section className="detail-section">
                  <div className="section-title-row">
                    <h3>Extracted claims</h3>
                    <span>{selected.claimCount}</span>
                  </div>
                  {selected.claims.length ? (
                    selected.claims.map((claim, index) => (
                      <article className="claim-card" key={claim.id}>
                        <div className="claim-topline">
                          <span>Claim {index + 1}</span>
                          <StatusBadge status={claim.status} />
                        </div>
                        <blockquote>{claim.text || claim.modelText}</blockquote>
                        <p>{claim.reason}</p>
                        <div className="object-classification">
                          <strong>{objectLabels[claim.primaryObject] ?? claim.primaryObject.replaceAll('_', ' ')}</strong>
                          <span>{claim.claimFocus.replaceAll('_', ' ')} · {claim.productMaturity.replaceAll('_', ' ')}</span>
                          <p>{claim.objectReason}</p>
                          {claim.unitInstanceCount > 1 && <small>One unique statement linked to {claim.unitInstanceCount} overlapping claim records.</small>}
                        </div>
                        <dl>
                          <div>
                            <dt>Domain</dt>
                            <dd>{claim.domain.replaceAll('_', ' ')}</dd>
                          </div>
                          <div>
                            <dt>Stance</dt>
                            <dd>{claim.type.replaceAll('_', ' ')}</dd>
                          </div>
                          <div>
                            <dt>Scientific position</dt>
                            <dd>{claim.consensus.replaceAll('_', ' ')}</dd>
                          </div>
                          <div>
                            <dt>Exaggeration</dt>
                            <dd>{claim.exaggeration}</dd>
                          </div>
                          <div>
                            <dt>Quote match</dt>
                            <dd>{claim.matchMethod.replaceAll('_', ' ')}</dd>
                          </div>
                          <div><dt>Extraction quality</dt><dd>{claim.extractionQuality.replaceAll('_', ' ')}</dd></div>
                          {claim.secondaryObjects.length > 0 && <div><dt>Also concerns</dt><dd>{claim.secondaryObjects.map(value => objectLabels[value] ?? value.replaceAll('_', ' ')).join(', ')}</dd></div>}
                        </dl>
                      </article>
                    ))
                  ) : (
                    <p className="muted-copy">
                      {selected.stage05Requested ? 'No assessable health/science claim was extracted from this window.' : 'This window screened negative for health and science in Stage 04 and did not receive claim classification.'}
                    </p>
                  )}
                </section>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </main>
  );
}
