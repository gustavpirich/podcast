'use client';

import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Layers3 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export type ProductClaim = {
  id: string; text: string; status: string; consensus: string; exaggeration: string;
  statementUnitId: string; unitInstanceCount: number; primaryObject: string;
  secondaryObjects: string[]; claimFocus: string; productMaturity: string;
  extractionQuality: string; objectReason: string;
};
export type ProductStatement = {
  window: { id: string; show: string; episodeTitle: string; guest: string; windowId: number };
  claim: ProductClaim;
};

const PAGE_SIZE = 40;
const labels: Record<string, string> = {
  vaccines_immunization: 'Vaccines & immunization', pharmaceuticals_biologics: 'Pharmaceuticals & biologics',
  peptides_hormones: 'Peptides & hormones', supplements_nutraceuticals: 'Supplements & nutraceuticals',
  psychoactive_substances: 'Psychoactive substances', medical_procedures_devices: 'Medical procedures & devices',
  diet_nutrition: 'Diet & nutrition', exercise_physical_activity: 'Exercise & physical activity',
  sleep_recovery: 'Sleep & recovery', mental_behavioral_interventions: 'Mental & behavioral interventions',
  environmental_lifestyle_exposures: 'Environmental & lifestyle exposures', healthcare_public_health: 'Healthcare & public health',
  disease_condition: 'Disease or condition', non_health_science: 'Non-health science', other_health: 'Other health', unclear: 'Unclear',
};

export function ProductOverview({ statements, totalUnits, repeatedInstances, onSelect, onObject }: {
  statements: ProductStatement[]; totalUnits: number; repeatedInstances: number;
  onSelect: (windowId: string) => void; onObject: (value: string) => void;
}) {
  const [page, setPage] = useState(1);
  const summaries = useMemo(() => {
    const map = new Map<string, { category: string; count: number; fringe: number; uncertain: number; jre: number; doac: number }>();
    for (const { window, claim } of statements) {
      const item = map.get(claim.primaryObject) ?? { category: claim.primaryObject, count: 0, fringe: 0, uncertain: 0, jre: 0, doac: 0 };
      item.count++;
      item.fringe += Number(claim.status === 'fringe');
      item.uncertain += Number(claim.status === 'uncertain');
      if (window.show === 'jre') item.jre++; else if (window.show === 'doac') item.doac++;
      map.set(claim.primaryObject, item);
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [statements]);
  const max = Math.max(...summaries.map(item => item.count), 1);
  const pages = Math.max(1, Math.ceil(statements.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  const visible = statements.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  return <div className="product-overview">
    <header className="product-heading">
      <div><span className="eyebrow">Unique statement units</span><h2>Health products, interventions & behaviors</h2>
        <p>{statements.length.toLocaleString()} selected of {totalUnits.toLocaleString()} units. {repeatedInstances.toLocaleString()} overlapping claim records are linked to their representative statement.</p></div>
      <div className="product-unit-note"><Layers3 /><span>Counts use deduplicated statements<br /><small>Categories are provisional</small></span></div>
    </header>
    <section className="object-summary-grid" aria-label="Product category distribution">
      {summaries.map(item => <button key={item.category} className="object-summary-card" onClick={() => onObject(item.category)}>
        <span><strong>{labels[item.category] ?? item.category.replaceAll('_', ' ')}</strong><b>{item.count.toLocaleString()}</b></span>
        <div className="object-count-track"><i style={{ width: `${100 * item.count / max}%` }} /></div>
        <small>{item.jre} JRE · {item.doac} DOAC · {item.fringe} broad fringe · {item.uncertain} uncertain</small>
      </button>)}
    </section>
    <section className="statement-list">
      <div className="statement-list-heading"><div><h3>Statements</h3><p>Click a statement to see its transcript window and complete scientific assessment.</p></div><span>{statements.length.toLocaleString()} units</span></div>
      {visible.map(({ window, claim }) => <button key={claim.statementUnitId} className="statement-row" onClick={() => onSelect(window.id)}>
        <span className="statement-object"><Badge variant="outline">{labels[claim.primaryObject] ?? claim.primaryObject.replaceAll('_', ' ')}</Badge><small>{claim.claimFocus.replaceAll('_', ' ')} · {claim.productMaturity.replaceAll('_', ' ')}</small></span>
        <span className="statement-copy"><strong>{claim.text}</strong><small>{window.show.toUpperCase()} · {window.guest || window.episodeTitle} · window {window.windowId}</small></span>
        <span className={`statement-status status-${claim.status === 'not_fringe' ? 'supported' : claim.status}`}>{claim.status.replaceAll('_', ' ')}</span>
      </button>)}
      {!statements.length && <div className="empty-state"><Layers3 /><strong>No statement units match these filters</strong><span>Clear or broaden a filter to continue.</span></div>}
      <footer className="pagination-bar"><span>{statements.length ? `${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, statements.length)} of ${statements.length.toLocaleString()}` : '0 results'}</span>
        <div><Button variant="outline" size="icon-sm" disabled={currentPage <= 1} onClick={() => setPage(value => Math.max(1, value - 1))}><ChevronLeft /></Button><span>Page {currentPage} of {pages}</span><Button variant="outline" size="icon-sm" disabled={currentPage >= pages} onClick={() => setPage(value => Math.min(pages, value + 1))}><ChevronRight /></Button></div></footer>
    </section>
    <p className="extent-caveat">Product categories describe what a statement concerns. They do not determine whether it is scientifically mainstream, exaggerated, safe, effective, or misinformation. Those existing labels remain separate.</p>
  </div>;
}
