export type SpaceNode = { id:string; label:string; kind:'motif'|'artifact'|'material'|'period'|'concept'; sub?:string; image?:string };
export type SpaceEdge = { id:string; from:string; to:string; label:string };
export function drawSpace(host:HTMLElement,nodes:SpaceNode[],edges:SpaceEdge[],picked:string,onEdge:(id:string)=>void,onNode:(id:string)=>void):()=>void;
