import { useEffect, useRef } from 'react';
import { drawSpace, type SpaceNode, type SpaceEdge } from './spatial-graph.js';
import './folio.css';

export function SpaceGraph(props: { nodes: SpaceNode[]; edges: SpaceEdge[]; picked: string; onEdge:(id:string)=>void; onNode:(id:string)=>void }) {
  const host=useRef<HTMLDivElement>(null);
  const dispose=useRef<(()=>void)|undefined>(undefined);
  useEffect(()=>{
    if (host.current) dispose.current=drawSpace(host.current,props.nodes,props.edges,props.picked,props.onEdge,props.onNode);
  },[props]);
  useEffect(()=>()=>dispose.current?.(),[]);
  return <div ref={host} className="space-graph" />;
}
