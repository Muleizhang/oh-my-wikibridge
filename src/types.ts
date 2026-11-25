export type Corpus = { id: string; name: string; description: string; revision: number; documentCount: number };
export type Source = {
  id: string; name: string; extension: string; bytes: number; sha256: string;
  status: 'queued' | 'processing' | 'failed' | 'draft' | 'published' | 'archived';
  error: string | null; unitCount: number; createdAt: string;
};
export type ImportResult = { source: Source; needsExtraction: boolean; duplicate: boolean };
export type Unit = { kind: string; ordinal: number; locator: string; text: string; method: 'native' | 'ocr'; confidence?: number };
export type Evidence = {
  id: string; sourceId: string; corpusId: string; corpusName: string; sourceName: string;
  extension: string; bytes: number; sha256: string; kind: string; ordinal: number;
  previewUrl?: string; captionUrl?: string; bbox?: number[];
  locator: string; text: string; method: string; confidence: number | null;
};
export type Fact = { subject: string; relation: string; object: string; evidenceId: string };
export type Review = { evidence: Evidence[]; factCount: number; ocrCount: number; lowConfidenceCount: number };
export type Hit = { evidence: Evidence; score: number };
export type Trace = { tool: string; detail: string; evidenceIds: string[] };
export type SearchResult = { hits: Hit[]; trace: Trace[] };
export type Answer = { answer: string | null; error: string | null; evidence: Evidence[]; trace: Trace[]; model: string | null };
export type Analytics = {
  sampleSize: number; topTerms: [string, number][]; pairs: [string, string, number][];
  projection: [string, number, number][]; neighbors: [string, number][];
};
export type BackendStatus = { detected: boolean; version: string | null; model: string | null; installUrl: string; remoteAllowed: boolean };
