import type { MotifRow } from './motif-data';
export function drawNetwork(host: HTMLElement, groups: MotifRow[][], picked: string, onPick: (id: string) => void, resolveImage?: (url: string) => string): (()=>void) | undefined;
