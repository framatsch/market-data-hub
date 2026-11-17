import type { ProviderUsage, UsagePeriod } from '../types';

export const BUDGET_KEYS = ['request_budget_per_day', 'request_budget_per_month'] as const;
export type BudgetKey = (typeof BUDGET_KEYS)[number];

/** A provider is metered when its connection config carries the request budgets. */
export function isMetered(connectionConfig: Record<string, unknown> | undefined): boolean {
  return !!connectionConfig && BUDGET_KEYS.some((key) => key in connectionConfig);
}

/** Parse a budget input: a non-negative integer, 0 meaning "no limit". */
export function parseBudget(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const value = Number(text);
  return Number.isSafeInteger(value) ? value : null;
}

export function describeUsage(period: UsagePeriod): string {
  return `${period.used} / ${period.budget > 0 ? period.budget : 'no limit'}`;
}

export function describeSharing(usage: Pick<ProviderUsage, 'shared'>): string {
  return usage.shared
    ? 'Counted across all replicas (Redis).'
    : 'Counted on this replica only (Redis unavailable).';
}
