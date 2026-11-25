export function normalizeKG(raw: unknown): any;
export function createKGReasoner(rawData: unknown): any;
export function eraInfo(label: string): { group: string; order: number; sub: number };
export function materialClass(label: string): string | null;
export function motifFamily(label: string): string | null;
export const PREDICATE_LABELS: Record<string, string>;
export const EXTRA_DIMENSIONS: Record<string, { predicate: string; field: string; label: string }>;
export const COMPARISON_DIMENSIONS: typeof EXTRA_DIMENSIONS;
export const PREDICTION_DIMENSIONS: Record<string, { kind: string; predicate: string; field: string; label: string }>;
