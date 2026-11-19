import { invoke, isTauri } from '@tauri-apps/api/core';
import { fixture } from './fixture';
import type { Evidence, Source } from './types';

export const desktop = isTauri();

export function call<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  return desktop ? invoke<T>(command, args) : fixture(command, args) as Promise<T>;
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function readRange(source: Pick<Source | Evidence, 'bytes'>, sourceId: string, offset: number, length: number, token?: string) {
  if (length > source.bytes - offset) throw new Error('File range exceeds source bounds.');
  return call<ArrayBuffer>('read_source_range', { sourceId, offset, length, token });
}

export async function readMedia(sourceId: string, bytes: number, token?: string): Promise<Blob> {
  const blocks: ArrayBuffer[] = [];
  for (let begin = 0; begin < bytes; begin += 8 * 1024 * 1024) {
    blocks.push(await readRange({ bytes }, sourceId, begin, Math.min(bytes - begin, 8 * 1024 * 1024), token));
  }
  return new Blob(blocks);
}
