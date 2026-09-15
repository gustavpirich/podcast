'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  SkipForward,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

type ModelStatus = 'fringe' | 'uncertain' | 'not_fringe';
type HumanStatus = ModelStatus | 'not_claim';
type ReviewClaim = {
  id: string;
  text: string;
  modelText: string;
  domain: string;
  type: string;
  consensus: string;
  exaggeration: string;
  advancedStatus: string;
  status: ModelStatus;
  modelStatus: ModelStatus;
  reason: string;
  matchMethod: string;
  textMatched: boolean;
  codingConsistent: boolean;
};
type SourceReviewClaim = Omit<ReviewClaim, 'status' | 'modelStatus'> & {
  status: ModelStatus | 'not_assessable' | 'not_screened';
  modelStatus: ModelStatus | 'not_assessable' | 'not_screened';
};
type ReviewWindow = {
  id: string;
  show: string;
  episodeId: string;
  episodeTitle: string;
  windowId: number;
  startMs: number;
  speakers: string[];
  snippet: string;
  health: boolean;
  science: boolean;
  claims: SourceReviewClaim[];
};
type ReviewDecision = {
  claimId: string;
  windowId: string;
  show: string;
  episodeId: string;
  episodeTitle: string;
  windowNumber: number;
  claimText: string;
  claimDomain: string;
  claimType: string;
  consensusRelation: string;
  exaggeration: string;
  advancedStatus: string;
  sourceHash: string;
  modelStatus: ModelStatus;
  humanStatus: HumanStatus;
  note: string;
  reviewedAt: string;
};

const STORAGE_KEY = 'classification-inspector-broad-reviews-v1';
const modelLabels: Record<ModelStatus, string> = {
  fringe: 'Fringe',
  uncertain: 'Uncertain',
  not_fringe: 'Not fringe',
};
const humanLabels: Record<HumanStatus, { title: string; detail: string }> = {
  fringe: {
    title: 'Broad fringe',
    detail:
      'Emerging non-mainstream, alternative/speculative, contradicting consensus, or materially exaggerated.',
  },
  uncertain: {
    title: 'Uncertain',
    detail:
      'Evidence is mixed, evolving, specialized, missing, or insufficient for a reliable judgment.',
  },
  not_fringe: {
    title: 'Not fringe',
    detail:
      'Within mainstream scientific understanding or debate, without material exaggeration.',
  },
  not_claim: {
    title: 'Not a claim',
    detail:
      'The extracted text is not a precise, checkable health or science assertion.',
  },
};

function stableScore(value: string) {
  let score = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    score ^= value.charCodeAt(index);
    score = Math.imul(score, 16777619);
  }
  return score >>> 0;
}

function interleave(
  items: Array<{ window: ReviewWindow; claim: ReviewClaim }>,
) {
  const buckets = (['uncertain', 'fringe', 'not_fringe'] as ModelStatus[]).map(
    (status) =>
      items
        .filter((item) => item.claim.status === status)
        .sort((a, b) => stableScore(a.claim.id) - stableScore(b.claim.id)),
  );
  const mixed: typeof items = [];
  for (
    let index = 0;
    buckets.some((bucket) => index < bucket.length);
    index += 1
  ) {
    for (const bucket of buckets) if (bucket[index]) mixed.push(bucket[index]);
  }
  return mixed;
}

function csvCell(value: string | number) {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${hours ? `${hours}:` : ''}${String(minutes).padStart(hours ? 2 : 1, '0')}:${String(remainder).padStart(2, '0')}`;
}

function HighlightedSnippet({
  snippet,
  claim,
}: {
  snippet: string;
  claim: string;
}) {
  if (!claim) return <>{snippet}</>;
  const start = snippet.toLocaleLowerCase().indexOf(claim.toLocaleLowerCase());
  if (start < 0) return <>{snippet}</>;
  return (
    <>
      {snippet.slice(0, start)}
      <mark>{snippet.slice(start, start + claim.length)}</mark>
      {snippet.slice(start + claim.length)}
    </>
  );
}

export function ReviewWorkspace({ rows, sourceHash, positionFilter, exaggerationFilter, stanceFilter }: {
  rows: ReviewWindow[]; sourceHash: string; positionFilter: string; exaggerationFilter: string; stanceFilter: string;
}) {
  const storageKey = `${STORAGE_KEY}:${sourceHash}`;
  const [target, setTarget] = useState<'mixed' | ModelStatus>('mixed');
  const [includeReviewed, setIncludeReviewed] = useState(false);
  const [position, setPosition] = useState(0);
  const [decisions, setDecisions] = useState<Record<string, ReviewDecision>>(
    {},
  );
  const [storageReady, setStorageReady] = useState(false);
  const [note, setNote] = useState('');
  const [storageError, setStorageError] = useState('');

  useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) setDecisions(JSON.parse(stored));
    } catch {
      setDecisions({});
      setStorageError('Saved reviews could not be read. Export any new decisions before leaving this page.');
    } finally {
      setStorageReady(true);
    }
  }, []);
  useEffect(() => {
    if (storageReady) {
      try { localStorage.setItem(storageKey, JSON.stringify(decisions)); }
      catch { setStorageError('Browser storage is unavailable. Export your decisions before leaving this page.'); }
    }
  }, [decisions, storageReady]);

  const allItems = useMemo(
    () =>
      rows.flatMap((window) =>
        window.claims.flatMap((claim) =>
          (claim.status !== 'fringe' && claim.status !== 'uncertain' && claim.status !== 'not_fringe') ||
          (positionFilter !== 'all' && claim.consensus !== positionFilter) ||
          (exaggerationFilter !== 'all' && claim.exaggeration !== exaggerationFilter) ||
          (stanceFilter !== 'all' && claim.type !== stanceFilter)
            ? []
            : [{ window, claim: claim as ReviewClaim }],
        ),
      ),
    [rows, positionFilter, exaggerationFilter, stanceFilter],
  );
  const queue = useMemo(() => {
    const selected = allItems.filter(
      (item) =>
        (target === 'mixed' || item.claim.status === target) &&
        (includeReviewed || !decisions[item.claim.id]),
    );
    return target === 'mixed'
      ? interleave(selected)
      : selected.sort(
          (a, b) => stableScore(a.claim.id) - stableScore(b.claim.id),
        );
  }, [allItems, target, includeReviewed, decisions]);
  useEffect(() => {
    if (position >= queue.length) setPosition(Math.max(queue.length - 1, 0));
  }, [position, queue.length]);
  const active = queue[position];
  useEffect(() => {
    setNote(active ? (decisions[active.claim.id]?.note ?? '') : '');
  }, [active?.claim.id, decisions]);

  function saveDecision(humanStatus: HumanStatus) {
    if (!active) return;
    const { window, claim } = active;
    setDecisions((current) => ({
      ...current,
      [claim.id]: {
        claimId: claim.id,
        windowId: window.id,
        show: window.show,
        episodeId: window.episodeId,
        episodeTitle: window.episodeTitle,
        windowNumber: window.windowId,
        claimText: claim.text || claim.modelText,
        claimDomain: claim.domain,
        claimType: claim.type,
        consensusRelation: claim.consensus,
        exaggeration: claim.exaggeration,
        advancedStatus: claim.advancedStatus,
        sourceHash,
        modelStatus: claim.status,
        humanStatus,
        note: note.trim(),
        reviewedAt: new Date().toISOString(),
      },
    }));
  }

  function exportReviews() {
    const values = Object.values(decisions).sort((a, b) =>
      a.reviewedAt.localeCompare(b.reviewedAt),
    );
    const headers = [
      'claim_id',
      'window_id',
      'show',
      'episode_id',
      'episode_title',
      'window_number',
      'claim_text',
      'claim_domain',
      'stance',
      'scientific_position',
      'exaggeration',
      'advanced_status',
      'source_sha256',
      'model_status',
      'human_status',
      'review_note',
      'reviewed_at',
    ];
    const lines = [headers.join(',')];
    for (const item of values) {
      lines.push(
        [
          item.claimId,
          item.windowId,
          item.show,
          item.episodeId,
          item.episodeTitle,
          item.windowNumber,
          item.claimText,
          item.claimDomain,
          item.claimType,
          item.consensusRelation,
          item.exaggeration,
          item.advancedStatus,
          item.sourceHash,
          item.modelStatus,
          item.humanStatus,
          item.note,
          item.reviewedAt,
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
    anchor.download = `human-claim-reviews-${values.length}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const reviewedCounts = Object.values(decisions).reduce(
    (counts, item) => ({
      ...counts,
      [item.humanStatus]: counts[item.humanStatus] + 1,
    }),
    { fringe: 0, uncertain: 0, not_fringe: 0, not_claim: 0 } as Record<
      HumanStatus,
      number
    >,
  );

  return (
    <div className="review-workspace">
      <header className="review-toolbar">
        <div>
          <span className="eyebrow">Human validation</span>
          <h2>Claim review queue</h2>
          <p>Decisions are saved only in this browser until you export them. They do not change the model totals.</p>
          {storageError && <p role="alert">{storageError}</p>}
        </div>
        <div className="review-controls">
          <Select
            value={target}
            onValueChange={(value) => {
              setTarget((value ?? 'mixed') as typeof target);
              setPosition(0);
            }}
          >
            <SelectTrigger aria-label="Choose claim review category">
              <SelectValue placeholder="Mixed review" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="mixed">Mixed: rotate all three</SelectItem>
              <SelectItem value="uncertain">Model: uncertain</SelectItem>
              <SelectItem value="fringe">Model: fringe</SelectItem>
              <SelectItem value="not_fringe">Model: not fringe</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => setIncludeReviewed((value) => !value)}
          >
            {includeReviewed ? <EyeOff /> : <Eye />}{' '}
            {includeReviewed ? 'Hide reviewed' : 'Show reviewed'}
          </Button>
          <Button
            variant="outline"
            disabled={!Object.keys(decisions).length}
            onClick={exportReviews}
          >
            <Download /> Export {Object.keys(decisions).length || ''}
          </Button>
        </div>
      </header>

      <div className="review-progress">
        <div>
          <span>Queue</span>
          <strong>{queue.length.toLocaleString()} remaining</strong>
        </div>
        <div>
          <span>Reviewed</span>
          <strong>{Object.keys(decisions).length.toLocaleString()}</strong>
        </div>
        <div>
          <span>Human fringe</span>
          <strong>{reviewedCounts.fringe}</strong>
        </div>
        <div>
          <span>Human uncertain</span>
          <strong>{reviewedCounts.uncertain}</strong>
        </div>
        <div>
          <span>Human not fringe</span>
          <strong>{reviewedCounts.not_fringe}</strong>
        </div>
        <div>
          <span>Not a claim</span>
          <strong>{reviewedCounts.not_claim}</strong>
        </div>
      </div>

      {active ? (
        <div className="review-card">
          <div className="review-context">
            <div className="review-meta">
              <Badge variant="outline">
                {active.window.show.toUpperCase()}
              </Badge>
              <span>Window {active.window.windowId}</span>
              <span>{formatTime(active.window.startMs)}</span>
              <span>{active.window.speakers.join(', ')}</span>
            </div>
            <h3>{active.window.episodeTitle}</h3>
            <div className="model-claim">
              <div>
                <span>Model extracted claim</span>
                <Badge
                  className={`status-${active.claim.status === 'not_fringe' ? 'supported' : active.claim.status}`}
                >
                  {modelLabels[active.claim.status]}
                </Badge>
              </div>
              <blockquote>
                {active.claim.text || active.claim.modelText}
              </blockquote>
              <p>{active.claim.reason}</p>
              <dl>
                <div>
                  <dt>Domain</dt>
                  <dd>{active.claim.domain.replaceAll('_', ' ')}</dd>
                </div>
                <div>
                  <dt>Stance</dt>
                  <dd>{active.claim.type.replaceAll('_', ' ')}</dd>
                </div>
                <div>
                  <dt>Scientific position</dt>
                  <dd>{active.claim.consensus.replaceAll('_', ' ')}</dd>
                </div>
                <div><dt>Exaggeration</dt><dd>{active.claim.exaggeration}</dd></div>
                <div>
                  <dt>Quotation match</dt>
                  <dd>{active.claim.matchMethod.replaceAll('_', ' ')}</dd>
                </div>
              </dl>
              {!active.claim.textMatched && <p className="review-alert">Quotation could not be matched to this window. Its final label is uncertain; check the transcript before accepting the extraction.</p>}
            </div>
            <section className="review-transcript">
              <span>Full 256-word context</span>
              <p>
                <HighlightedSnippet
                  snippet={active.window.snippet}
                  claim={active.claim.text}
                />
              </p>
            </section>
          </div>

          <aside className="human-coding-panel">
            <div>
              <span className="eyebrow">Your assessment</span>
              <h3>How should this claim be coded?</h3>
              <p>
                Judge the claim as spoken in context. Add a note when the
                boundary or evidence needed is unclear.
              </p>
            </div>
            <div className="human-labels">
              {(Object.keys(humanLabels) as HumanStatus[]).map(
                (humanStatus) => (
                  <button
                    key={humanStatus}
                    className={`human-label human-${humanStatus}`}
                    data-selected={
                      decisions[active.claim.id]?.humanStatus === humanStatus
                    }
                    onClick={() => saveDecision(humanStatus)}
                  >
                    <span>{humanLabels[humanStatus].title}</span>
                    <small>{humanLabels[humanStatus].detail}</small>
                    {decisions[active.claim.id]?.humanStatus ===
                      humanStatus && <Check />}
                  </button>
                ),
              )}
            </div>
            <label className="review-note">
              <span>
                Review note <small>optional</small>
              </span>
              <Textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Evidence needed, ambiguity, or prompt correction…"
              />
            </label>
            {decisions[active.claim.id] &&
              note !== decisions[active.claim.id].note && (
                <p className="unsaved-note">
                  <AlertTriangle /> Choose a label again to save the edited
                  note.
                </p>
              )}
          </aside>
          <footer className="review-navigation">
            <Button
              variant="outline"
              disabled={position === 0}
              onClick={() => setPosition((value) => Math.max(value - 1, 0))}
            >
              <ChevronLeft /> Previous
            </Button>
            <span>
              {position + 1} of {queue.length.toLocaleString()}
            </span>
            <Button
              variant="outline"
              onClick={() =>
                setPosition((value) => Math.min(value + 1, queue.length - 1))
              }
            >
              <SkipForward /> Skip
            </Button>
            <Button
              disabled={position >= queue.length - 1}
              onClick={() =>
                setPosition((value) => Math.min(value + 1, queue.length - 1))
              }
            >
              Next <ChevronRight />
            </Button>
          </footer>
        </div>
      ) : (
        <div className="review-empty">
          <Check />
          <h3>No unreviewed claims remain in this selection</h3>
          <p>
            Show reviewed claims, change the category, or broaden the dashboard
            filters.
          </p>
          <Button
            variant="outline"
            disabled={!Object.keys(decisions).length}
            onClick={exportReviews}
          >
            <Download /> Export review decisions
          </Button>
        </div>
      )}
    </div>
  );
}
