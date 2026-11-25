export function normalizeKG(raw: unknown): any;
export function createKGReasoner(rawData: unknown): any;
export function eraInfo(label: string): { group: string; order: number; sub: number };
export function materialClass(label: string): string | null;
export function motifFamily(label: string): string | null;
export const PREDICATE_LABELS: Record<string, string>;
