import type { MotifRow } from './motif-data';
export function drawNetwork(svg: SVGSVGElement, groups: MotifRow[][], picked: string, onPick: (id: string) => void): void;
