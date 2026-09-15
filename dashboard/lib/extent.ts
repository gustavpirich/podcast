export type ExtentRow = {
  id: string;
  show: string;
  episodeId: string;
  episodeTitle: string;
  guest: string;
  publishedDate: string;
  windowId: number;
  status: string;
  advancedStatus: string;
  stage05Requested: boolean;
  claims: Array<{ consensus: string; exaggeration: string; textMatched: boolean }>;
};

export const categories = {
  emerging_non_mainstream: 'Emerging non-mainstream',
  alternative_speculative: 'Alternative / speculative',
  contradicts_consensus: 'Contradicts consensus',
  exaggerated: 'Exaggerated',
} as const;

export function summarizeExtent(rows: ExtentRow[]) {
  const episodes = new Map<string, {
    show: string; episodeId: string; title: string; guest: string;
    windows: number; screened: number; present: number; advanced: number; uncertain: number;
  }>();
  const shows = new Map<string, { show: string; windows: number; screened: number; present: number; advanced: number; uncertain: number; categories: Record<string, number> }>();
  for (const row of rows) {
    const key = `${row.show}:${row.episodeId}`;
    const episode = episodes.get(key) ?? { show: row.show, episodeId: row.episodeId,
      title: row.episodeTitle, guest: row.guest, windows: 0, screened: 0, present: 0, advanced: 0, uncertain: 0 };
    const show = shows.get(row.show) ?? { show: row.show, windows: 0, screened: 0,
      present: 0, advanced: 0, uncertain: 0, categories: Object.fromEntries(Object.keys(categories).map(key => [key, 0])) };
    for (const group of [episode, show]) {
      group.windows++;
      group.screened += Number(row.stage05Requested);
      group.present += Number(row.status === 'fringe');
      group.advanced += Number(row.advancedStatus === 'fringe');
      group.uncertain += Number(row.status === 'uncertain');
    }
    for (const key of Object.keys(categories)) {
      show.categories[key] += Number(row.claims.some(claim => claim.textMatched &&
        (key === 'exaggerated' ? claim.exaggeration === 'yes' : claim.consensus === key)));
    }
    episodes.set(key, episode);
    shows.set(row.show, show);
  }
  return { episodes: [...episodes.values()].sort((a, b) => b.present / b.windows - a.present / a.windows),
    shows: [...shows.values()].sort((a, b) => a.show.localeCompare(b.show)) };
}
