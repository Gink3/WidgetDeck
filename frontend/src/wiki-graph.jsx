import React, { useEffect, useMemo, useState } from "react";
import { ReactFlow, Background, Controls, MiniMap, MarkerType, applyNodeChanges } from "@xyflow/react";
import flowStyles from "@xyflow/react/dist/style.css?inline";
import { api } from "./wiki-api.mjs";
import "./wiki-graph.css";

const bands = [[0, "#64748b", "0"], [2, "#287bb5", "1–2"], [5, "#258372", "3–5"], [10, "#a16a14", "6–10"], [Infinity, "#9a51ad", "11+"]];
const color = count => bands.find(([limit]) => count <= limit)[1];

// A spanning forest gives each connected group a starting shape. Cross-links
// and cycles remain visible; dragging never changes the underlying wiki links.
function arrange(pages, edges) {
  const neighbors = new Map(pages.map(p => [p.id, new Set()]));
  edges.forEach(e => { neighbors.get(e.source)?.add(e.target); neighbors.get(e.target)?.add(e.source); });
  const placed = new Set(), positions = {};
  let row = 0;
  const roots = [...pages].sort((a, b) => (b.incoming + b.outgoing) - (a.incoming + a.outgoing));
  for (const root of roots) {
    if (placed.has(root.id)) continue;
    const queue = [{ id: root.id, depth: 0 }], levels = new Map();
    placed.add(root.id);
    for (let i = 0; i < queue.length; i++) {
      const item = queue[i];
      if (!levels.has(item.depth)) levels.set(item.depth, []);
      levels.get(item.depth).push(item.id);
      for (const next of neighbors.get(item.id)) if (!placed.has(next)) {
        placed.add(next); queue.push({ id: next, depth: item.depth + 1 });
      }
    }
    const height = Math.max(...[...levels.values()].map(ids => ids.length));
    for (const [depth, ids] of levels) ids.forEach((id, i) => {
      positions[id] = { x: depth * 290, y: (row + i + (height - ids.length) / 2) * 120 };
    });
    row += height + 1;
  }
  return positions;
}

export function WikiGraph() {
  const [graph, setGraph] = useState(null), [nodes, setNodes] = useState([]);
  const [error, setError] = useState(""), [selected, setSelected] = useState(null);
  const [query, setQuery] = useState(""), [flow, setFlow] = useState(null);
  const [loading, setLoading] = useState(false);
  const key = graph ? `wiki-graph-layout:${graph.owner_id}` : null;
  async function load() {
    setLoading(true); setError("");
    try {
      const g = await api("/graph");
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem(`wiki-graph-layout:${g.owner_id}`) || "{}"); } catch {}
      const positions = arrange(g.nodes, g.edges);
      setGraph(g);
      setSelected(null);
      setNodes(g.nodes.map(p => ({ id: p.id, position: Number.isFinite(saved[p.id]?.x) && Number.isFinite(saved[p.id]?.y) ? saved[p.id] : positions[p.id], data: { label: <><strong>{p.title}</strong><small>{p.incoming} in · {p.outgoing} out</small></> }, style: { background: color(p.incoming + p.outgoing), color: "white", border: "2px solid #ffffff55", width: 210 }, sourcePosition: "right", targetPosition: "left" })));
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  const edges = useMemo(() => (graph?.edges || []).map(e => ({ ...e, markerEnd: { type: MarkerType.ArrowClosed, color: "#aaa4ba" }, style: { stroke: selected && (e.source === selected || e.target === selected) ? "#79d2c7" : "#aaa4ba", strokeWidth: selected && (e.source === selected || e.target === selected) ? 3 : 1.5 } })), [graph, selected]);
  function persist(next) {
    try { localStorage.setItem(key, JSON.stringify(Object.fromEntries(next.map(n => [n.id, n.position])))); }
    catch { setError("Layout could not be saved in this browser."); }
  }
  const page = graph?.nodes.find(n => n.id === selected);
  const matches = graph?.nodes.filter(n => query.trim() && n.title.toLowerCase().includes(query.trim().toLowerCase())) || [];
  function focus(id) { setSelected(id); flow?.fitView({ nodes: [{ id }], maxZoom: 1.2, duration: 350 }); }
  return <section className="wiki-graph" aria-label="Wiki link map">
    <style>{flowStyles}</style>
    <div className="wiki-graph-tools">
      <h2>Page link map</h2>
      <button disabled={loading} onClick={load}>{loading ? "Loading…" : "Refresh links"}</button>
      <button disabled={!graph} onClick={() => { const positions = arrange(graph.nodes, graph.edges); const next = nodes.map(n => ({ ...n, position: positions[n.id] })); setNodes(next); persist(next); requestAnimationFrame(() => flow?.fitView({ duration: 350 })); }}>Arrange tree</button>
    </div>
    <p>Drag pages to arrange them. Pan and zoom to explore. Select a node for details. Arrows point from the linking page to its destination.</p>
    <div className="wiki-graph-legend" aria-label="Total incoming and outgoing links">Links in + out: {bands.map(([, c, label]) => <span key={label}><i style={{ background: c }} />{label}</span>)}</div>
    <p className="wiki-graph-count">{graph?.nodes.length || 0} pages · {graph?.edges.length || 0} directed links. Repeated links count once per destination; reciprocal links count in both directions.</p>
    <label>Find a page in the map<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Page title…" /></label>
    {query.trim() && <div className="wiki-graph-results">{matches.length ? matches.map(p => <button key={p.id} onClick={() => focus(p.id)}>{p.title}</button>) : <p>No matching pages.</p>}</div>}
    {error && <p role="alert">{error}</p>}
    {graph && !graph.nodes.length ? <p>Create pages and connect them with [[wiki links]] to build your map.</p> : <div className="wiki-graph-canvas">
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={changes => setNodes(current => applyNodeChanges(changes, current))} onNodeDragStop={(_, node) => persist(nodes.map(n => n.id === node.id ? node : n))} onNodeClick={(_, n) => setSelected(n.id)} onNodeDoubleClick={(_, n) => { const p = graph.nodes.find(p => p.id === n.id); location.href = `/tools/wiki/${p.slug}`; }} onInit={setFlow} fitView nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} minZoom={0.05} maxZoom={2}>
        <Background color="#514861" /><Controls showInteractive={false} /><MiniMap nodeColor={n => n.style.background} pannable zoomable />
      </ReactFlow>
    </div>}
    {page && <div className="wiki-graph-selection"><h3>{page.title}</h3><p>{page.incoming} incoming · {page.outgoing} outgoing · {page.incoming + page.outgoing} total</p><a href={`/tools/wiki/${page.slug}`}>Open page</a></div>}
  </section>;
}
