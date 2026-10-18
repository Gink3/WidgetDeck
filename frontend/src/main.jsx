import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  addEdge, applyEdgeChanges, applyNodeChanges, Background, Controls, Handle, MarkerType,
  MiniMap, Position, ReactFlow, ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './mindmaps.css';

const API = '/tools/mindmaps/api';
const types = ['topic', 'idea', 'question', 'note', 'reference', 'task'];
const typeLabels = { topic: 'Topic', idea: 'Idea', question: 'Question', note: 'Note', reference: 'Reference', task: 'Task' };
const uid = () => crypto.randomUUID();
const blankViewport = { x: 0, y: 0, zoom: 1 };

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'Something went wrong.');
  }
  return response.status === 204 ? null : response.json();
}

function newNode(title = 'New idea', x = 0, y = 0, type = 'idea') {
  return { id: uid(), title, description: '', x, y, width: 180, height: 44, type, collapsed: false, metadata: {}, style_override: {} };
}

function graphTemplate(kind) {
  const root = newNode(kind === 'Blank' ? 'Central idea' : kind, 0, 0, 'topic');
  const make = (title, x, y, type = 'idea') => newNode(title, x, y, type);
  const samples = {
    Blank: [],
    Brainstorm: [make('What if…', 290, -160, 'question'), make('Possibilities', 290, -50), make('Wild ideas', 290, 60), make('Next steps', 290, 170, 'task')],
    'Project Planning': [make('Goals', 290, -150, 'topic'), make('Scope', 290, -50), make('Milestones', 290, 50, 'task'), make('Risks', 290, 150, 'question')],
    Research: [make('Question', 290, -150, 'question'), make('Sources', 290, -50, 'reference'), make('Evidence', 290, 50, 'note'), make('Open threads', 290, 150, 'question')],
    'Decision Map': [make('Option A', 290, -100), make('Option B', 290, 0), make('Option C', 290, 100), make('Decision criteria', -300, 0, 'question')],
    'Concept Map': [make('Related concept', 290, -100), make('Example', 290, 50, 'reference'), make('Context', -290, 0, 'note')],
  };
  const nodes = [root, ...(samples[kind] || [])];
  const edges = nodes.slice(1).map((node) => ({ id: uid(), source_id: root.id, target_id: node.id, kind: 'hierarchy', label: '', directed: true }));
  if (kind === 'Decision Map') edges.push({ id: uid(), source_id: nodes[1].id, target_id: nodes[2].id, kind: 'relation', label: 'compare', directed: false });
  return { name: kind === 'Blank' ? 'Untitled mind map' : kind, description: '', viewport: blankViewport, layout_mode: 'freeform', settings: {}, nodes, edges };
}

function MindNode({ data, selected }) {
  const accent = data.style_override?.accent;
  return <div className={`mind-node type-${data.type} ${selected ? 'selected' : ''} ${data.dim ? 'dim' : ''}`} style={accent ? { '--node-accent': accent } : {}}>
    <Handle type="target" position={Position.Left} className="mind-handle" />
    <button className="node-collapse" onClick={(event) => { event.stopPropagation(); data.onCollapse(data.id); }} title={data.collapsed ? 'Expand branch' : 'Collapse branch'}>{data.collapsed ? '+' : '−'}</button>
    <div className="node-kind">{typeLabels[data.type]}</div><div className="node-title">{data.title}</div>
    {data.hiddenCount ? <div className="hidden-count">+ {data.hiddenCount} hidden</div> : null}
    <Handle type="source" position={Position.Right} className="mind-handle" />
  </div>;
}

const nodeTypes = { mind: MindNode };

function descendants(graph, seedIds) {
  const found = new Set(seedIds); let changed = true;
  while (changed) { changed = false; graph.edges.filter((edge) => edge.kind === 'hierarchy' && found.has(edge.source_id) && !found.has(edge.target_id)).forEach((edge) => { found.add(edge.target_id); changed = true; }); }
  return found;
}

function toFlow(graph, search, onCollapse, revealed = new Set()) {
  const children = new Map();
  graph.edges.filter((edge) => edge.kind === 'hierarchy').forEach((edge) => {
    if (!children.has(edge.source_id)) children.set(edge.source_id, []);
    children.get(edge.source_id).push(edge.target_id);
  });
  const hidden = new Set(); const hiddenCount = {};
  const hideDescendants = (id, ancestor) => (children.get(id) || []).forEach((child) => { if (revealed.has(child)) { hideDescendants(child, ancestor); return; } hidden.add(child); hiddenCount[ancestor] = (hiddenCount[ancestor] || 0) + 1; hideDescendants(child, ancestor); });
  graph.nodes.filter((node) => node.collapsed).forEach((node) => hideDescendants(node.id, node.id));
  const term = search.trim().toLowerCase();
  const nodes = graph.nodes.filter((node) => !hidden.has(node.id)).map((node) => ({
    id: node.id, type: 'mind', position: { x: node.x, y: node.y }, style: { width: node.width, minHeight: node.height },
    data: { ...node, hiddenCount: hiddenCount[node.id], dim: Boolean(term && !`${node.title} ${node.description} ${node.metadata?.url || ''}`.toLowerCase().includes(term)), onCollapse },
  }));
  const visible = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => visible.has(edge.source_id) && visible.has(edge.target_id)).map((edge) => ({
    id: edge.id, source: edge.source_id, target: edge.target_id, label: edge.label, animated: edge.kind === 'relation' && edge.directed,
    type: 'smoothstep', markerEnd: edge.directed ? { type: MarkerType.ArrowClosed } : undefined,
    className: edge.kind === 'hierarchy' ? 'hierarchy-edge' : 'relation-edge', data: edge,
  }));
  return { nodes, edges };
}

function exportSvg(graph) {
  const pad = 70; const xs = graph.nodes.map((node) => node.x); const ys = graph.nodes.map((node) => node.y);
  const left = Math.min(0, ...xs) - pad, top = Math.min(0, ...ys) - pad;
  const right = Math.max(300, ...graph.nodes.map((node) => node.x + node.width)) + pad;
  const bottom = Math.max(200, ...graph.nodes.map((node) => node.y + node.height)) + pad;
  const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[char]));
  const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
  const edges = graph.edges.map((edge) => { const a = byId[edge.source_id], b = byId[edge.target_id]; if (!a || !b) return ''; const x1 = a.x + a.width / 2, y1 = a.y + a.height / 2, x2 = b.x + b.width / 2, y2 = b.y + b.height / 2; return `<path d="M ${x1} ${y1} L ${x2} ${y2}" stroke="${edge.kind === 'hierarchy' ? '#a875ff' : '#79d2c7'}" stroke-width="2" fill="none" ${edge.directed ? 'marker-end="url(#arrow)"' : ''}/>${edge.label ? `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}" text-anchor="middle" fill="#aaa4ba" font-size="12">${esc(edge.label)}</text>` : ''}`; }).join('');
  const nodes = graph.nodes.map((node) => `<g><rect x="${node.x}" y="${node.y}" rx="7" width="${node.width}" height="${node.height}" fill="#211c2b" stroke="${node.style_override?.accent || '#a875ff'}"/><text x="${node.x + 14}" y="${node.y + 25}" fill="#eeeafa" font-family="Arial" font-size="14">${esc(node.title)}</text><text x="${node.x + 14}" y="${node.y + 40}" fill="#79d2c7" font-family="Arial" font-size="9">${esc(typeLabels[node.type].toUpperCase())}</text></g>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${left} ${top} ${right - left} ${bottom - top}" width="${right - left}" height="${bottom - top}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#79d2c7"/></marker></defs><rect x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" fill="#17141f"/>${edges}${nodes}</svg>`;
}

function download(name, content, mime) { const url = URL.createObjectURL(new Blob([content], { type: mime })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 500); }

function Layout({ graph, mode }) {
  const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
  const children = {}; const childIds = new Set();
  graph.edges.filter((edge) => edge.kind === 'hierarchy').forEach((edge) => { (children[edge.source_id] ||= []).push(edge.target_id); childIds.add(edge.target_id); });
  const roots = graph.nodes.filter((node) => !childIds.has(node.id)); if (!roots.length) return graph;
  const nodes = graph.nodes.map((node) => ({ ...node })); const result = Object.fromEntries(nodes.map((node) => [node.id, node]));
  if (mode === 'radial') {
    const root = roots[0]; result[root.id].x = 0; result[root.id].y = 0; const queue = [{ id: root.id, depth: 0 }]; const levels = {};
    while (queue.length) { const item = queue.shift(); (levels[item.depth] ||= []).push(item.id); (children[item.id] || []).forEach((id) => queue.push({ id, depth: item.depth + 1 })); }
    Object.entries(levels).forEach(([depthText, ids]) => { const depth = Number(depthText); if (!depth) return; ids.forEach((id, index) => { const angle = (Math.PI * 2 * index) / ids.length - Math.PI / 2; result[id].x = Math.cos(angle) * depth * 280; result[id].y = Math.sin(angle) * depth * 210; }); });
  } else {
    let cursor = 0;
    const place = (id, depth) => { const kids = children[id] || []; if (!kids.length) { result[id].y = cursor * 100; cursor += 1; } else { kids.forEach((child) => place(child, depth + 1)); result[id].y = (result[kids[0]].y + result[kids[kids.length - 1]].y) / 2; } result[id].x = depth * 280; };
    roots.forEach((root) => { place(root.id, 0); cursor += 1; });
  }
  return { ...graph, nodes };
}

function Library() {
  const [maps, setMaps] = useState([]); const [librarySearch,setLibrarySearch]=useState(''); const [error, setError] = useState(''); const inputRef = useRef();
  const load = useCallback(() => api('/maps').then(async ({ maps: items }) => {setMaps(items);const recent=await window.launcherLast?.('mind-maps');if(recent&&items.some(item=>item.id===recent.id)){location.replace(recent.url);return;}if(!location.search){try{const last=JSON.parse(localStorage.getItem('dashboard.workspace.last.v1.'+document.body.dataset.owner)||'{}')['/tools/mindmaps'];if(items.some(item=>item.id===last))location.replace('/tools/mindmaps/'+last);}catch(_){}}}).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const create = (kind = 'Blank') => { location.href='/tools/mindmaps/new?template='+encodeURIComponent(kind); };
  const remove = async (map) => { if (confirm(`Delete “${map.name}”? This cannot be undone.`)) { await api(`/maps/${map.id}`, { method: 'DELETE' }); load(); } };
  const duplicate = async (map) => { const { map: copy } = await api(`/maps/${map.id}/duplicate`, { method: 'POST' }); location.href = `/tools/mindmaps/${copy.id}`; };
  const importMap = async (event) => { const file = event.target.files?.[0]; if (!file) return; try { const document = JSON.parse(await file.text()); const { map } = await api('/maps/import', { method: 'POST', body: JSON.stringify({ map: document.map || document }) }); location.href = `/tools/mindmaps/${map.id}`; } catch (e) { setError(`Could not import that map: ${e.message}`); } finally { event.target.value = ''; } };
  return <main className="mind-library"><div className="library-heading"><div><h1 className="sr-only">Mind Maps</h1></div><div className="library-actions"><button className="primary" onClick={() => create()}>+ New map</button><details className="workspace-more"><summary>More</summary><div><button className="secondary" onClick={() => inputRef.current.click()}>Import JSON</button></div></details><input ref={inputRef} type="file" accept="application/json,.json,.mindmap" hidden onChange={importMap} /></div></div>{error ? <p className="error">{error}</p> : null}<details className="template-section"><summary>Start from a template</summary><div className="templates">{['Blank', 'Brainstorm', 'Project Planning', 'Research', 'Decision Map', 'Concept Map'].map((kind) => <button key={kind} className="template" onClick={() => create(kind)}><span>⌘</span><strong>{kind}</strong><small>{kind === 'Blank' ? 'A clean canvas' : 'A focused starting structure'}</small></button>)}</div></details><section className="map-section"><h2>Your maps</h2><input type="search" aria-label="Find a map" placeholder="Find a map" value={librarySearch} onChange={e=>setLibrarySearch(e.target.value)}/>{maps.length ? <div className="map-grid">{maps.filter(map=>(map.name+' '+map.description).toLowerCase().includes(librarySearch.toLowerCase())).map((map) => <article className="map-card" key={map.id}><a href={`/tools/mindmaps/${map.id}`}><p className="eyebrow">{map.layout_mode}</p><h3>{map.name}</h3><p>{map.description || 'No description yet.'}</p><small>Updated {new Date(map.updated_at).toLocaleString()}</small></a><details className="workspace-more"><summary>More</summary><div><button onClick={() => duplicate(map)}>Duplicate</button><a href={`/tools/mindmaps/api/maps/${map.id}/export`}>JSON</a><button className="danger-link" onClick={() => remove(map)}>Delete</button></div></details></article>)}</div> : <div className="empty-map"><h3>No maps yet</h3><p>Start a blank map or choose a template above.</p></div>}</section></main>;
}

function Editor() {
  const root = document.getElementById('mindmap-root'); const initialId = root.dataset.mapId;
  const [publishing,setPublishing]=useState(false);
  const [mapId, setMapId] = useState(initialId); const [graph, setGraph] = useState(null); const [selection, setSelection] = useState({ nodes: [], edges: [] }); const [search, setSearch] = useState(''); const [revealed, setRevealed] = useState(new Set()); const [connectKind, setConnectKind] = useState('hierarchy'); const [status, setStatus] = useState('Loading…'); const [error, setError] = useState(''); const [settings, setSettings] = useState({ minimap: true, grid: true, snap: false, default_node_type: 'idea' }); const [settingsOpen, setSettingsOpen] = useState(root.dataset.openSettings === 'true'); const [context, setContext] = useState(null); const [flow, setFlow] = useState(null);
  useEffect(()=>{if(!mapId||mapId==='new')return;try{const key='dashboard.workspace.last.v1.'+document.body.dataset.owner,last=JSON.parse(localStorage.getItem(key)||'{}');last['/tools/mindmaps']=mapId;localStorage.setItem(key,JSON.stringify(last));}catch(_){}},[mapId]);
  useEffect(()=>{if(mapId&&mapId!=='new')window.recordLauncherVisit?.('mind-maps',mapId);},[mapId]);
  const savedFingerprint=useRef(''),saveQueue=useRef(Promise.resolve()),savingRef=useRef(false);
  const fingerprint=item=>JSON.stringify({...item,updated_at:undefined});
  const graphVersion=graph?fingerprint(graph):'';
  const graphRef = useRef(graph); const history = useRef({ past: [], future: [] }); const loaded = useRef(false); const dragStart = useRef(null); const clipboard = useRef(null);
  useEffect(() => { graphRef.current = graph; }, [graph]);
  const load = useCallback(async () => { try { const [settingsResult, mapResult] = await Promise.all([api('/settings'), initialId === 'new' ? Promise.resolve({map:graphTemplate(new URLSearchParams(location.search).get('template')||'Blank')}) : api(`/maps/${initialId}`)]); setSettings({ minimap: true, grid: true, snap: false, default_node_type: 'idea', ...settingsResult.settings }); const item = mapResult.map; setMapId(item.id||'new'); savedFingerprint.current=item.id?fingerprint(item):''; setGraph(item); setStatus(item.id?'Saved':'Unsaved draft'); loaded.current = true; } catch (e) { setError(e.message); setStatus('Offline'); } }, [initialId]);
  useEffect(() => { load(); }, [load]);
  useEffect(()=>{const warn=e=>{if(loaded.current&&(savingRef.current||fingerprint(graphRef.current)!==savedFingerprint.current)){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
  const publish=async()=>{if(publishing)return;setPublishing(true);try{const snapshot=graphRef.current;const {map}=await api('/maps',{method:'POST',body:JSON.stringify(snapshot)});savedFingerprint.current=fingerprint(snapshot);setMapId(map.id);window.history.replaceState(null,'','/tools/mindmaps/'+map.id);setStatus('Saved');}catch(e){setError(e.message);}finally{setPublishing(false);}};
  const record = useCallback((before, after) => { history.current.past.push(before); if (history.current.past.length > 100) history.current.past.shift(); history.current.future = []; setGraph(after); }, []);
  const mutate = useCallback((fn) => { const before = structuredClone(graphRef.current); const after = fn(structuredClone(before)); record(before, after); }, [record]);
  const updateNode = (id, changes) => mutate((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === id ? { ...node, ...changes } : node) }));
  const addNode = useCallback((parentId = null, position = null) => { mutate((current) => { const parent = current.nodes.find((node) => node.id === parentId); const node = newNode('New idea', position?.x ?? ((parent?.x || 0) + 280), position?.y ?? ((parent?.y || 0) + 100), settings.default_node_type || 'idea'); return { ...current, nodes: [...current.nodes, node], edges: parent ? [...current.edges, { id: uid(), source_id: parent.id, target_id: node.id, kind: 'hierarchy', label: '', directed: true }] : current.edges }; }); }, [mutate, settings.default_node_type]);
  const parentFor = (id) => graphRef.current.edges.find((edge) => edge.kind === 'hierarchy' && edge.target_id === id)?.source_id;
  const addSibling = () => { const selected = selection.nodes[0]; if (!selected) return addNode(); const parent = parentFor(selected.id); addNode(parent, { x: selected.position.x, y: selected.position.y + 100 }); };
  const toggleCollapse = useCallback((id) => updateNode(id, { collapsed: !graphRef.current.nodes.find((node) => node.id === id)?.collapsed }), []);
  const removeSelection = () => mutate((current) => { const ids = descendants(current, selection.nodes.map((node) => node.id)); const edgeIds = new Set(selection.edges.map((edge) => edge.id)); return { ...current, nodes: current.nodes.filter((node) => !ids.has(node.id)), edges: current.edges.filter((edge) => !ids.has(edge.source_id) && !ids.has(edge.target_id) && !edgeIds.has(edge.id)) }; });
  const undo = useCallback(() => { const state = history.current; if (!state.past.length) return; const prior = state.past.pop(); state.future.push(structuredClone(graphRef.current)); setGraph(prior); }, []);
  const redo = useCallback(() => { const state = history.current; if (!state.future.length) return; const next = state.future.pop(); state.past.push(structuredClone(graphRef.current)); setGraph(next); }, []);
  useEffect(() => { const copyBranch = (event) => { if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'c' || event.target.matches('input, textarea, select')) return; const ids = descendants(graphRef.current, selection.nodes.map((node) => node.id)); if (!ids.size) return; clipboard.current = { nodes: graphRef.current.nodes.filter((node) => ids.has(node.id)), edges: graphRef.current.edges.filter((edge) => ids.has(edge.source_id) && ids.has(edge.target_id)) }; event.preventDefault(); event.stopImmediatePropagation(); }; window.addEventListener('keydown', copyBranch, true); return () => window.removeEventListener('keydown', copyBranch, true); }, [selection]);
  useEffect(() => { const keydown = (event) => { const target = event.target; if (target.matches('input, textarea, select, [contenteditable="true"], button, a, summary')||!target.closest('.canvas')) return; const modifier = event.metaKey || event.ctrlKey; if (modifier && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); } else if (modifier && event.key.toLowerCase() === 'y') { event.preventDefault(); redo(); } else if (modifier && event.key.toLowerCase() === 'c') { const ids = new Set(selection.nodes.map((node) => node.id)); clipboard.current = { nodes: graphRef.current.nodes.filter((node) => ids.has(node.id)), edges: graphRef.current.edges.filter((edge) => ids.has(edge.source_id) && ids.has(edge.target_id)) }; } else if (modifier && event.key.toLowerCase() === 'v' && clipboard.current?.nodes.length) { event.preventDefault(); mutate((current) => { const ids = Object.fromEntries(clipboard.current.nodes.map((node) => [node.id, uid()])); return { ...current, nodes: [...current.nodes, ...clipboard.current.nodes.map((node) => ({ ...node, id: ids[node.id], x: node.x + 45, y: node.y + 45 }))], edges: [...current.edges, ...clipboard.current.edges.map((edge) => ({ ...edge, id: uid(), source_id: ids[edge.source_id], target_id: ids[edge.target_id] }))] }; }); } else if (event.key === 'Enter') { event.preventDefault(); addSibling(); } else if (event.key === 'Tab') { event.preventDefault(); if (event.shiftKey) { const parent = selection.nodes[0] && parentFor(selection.nodes[0].id); if (parent) setSelection({ nodes: [{ id: parent }], edges: [] }); } else addNode(selection.nodes[0]?.id); } else if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeSelection(); } else if (event.key === 'F2') { event.preventDefault(); document.querySelector('.detail-title')?.focus(); } }; window.addEventListener('keydown', keydown); return () => window.removeEventListener('keydown', keydown); }, [addNode, addSibling, mutate, redo, removeSelection, selection, undo]);
  useEffect(() => {
    if(!graph||!loaded.current||mapId==='new'||fingerprint(graph)===savedFingerprint.current)return;
    setStatus('Unsaved changes');
    const timer=setTimeout(()=>{
      saveQueue.current=saveQueue.current.then(async()=>{
        const snapshot=graphRef.current,version=fingerprint(snapshot);
        if(version===savedFingerprint.current)return;
        savingRef.current=true;setStatus('Saving…');
        try{await api(`/maps/${mapId}`,{method:'PUT',body:JSON.stringify(snapshot)});savedFingerprint.current=version;setStatus(fingerprint(graphRef.current)===version?'Saved':'Unsaved changes');setError('');}
        catch(e){setError(e.message);setStatus('Offline');}
        finally{savingRef.current=false;}
      });
    },700);
    return()=>clearTimeout(timer);
  },[graphVersion,mapId]);
  const onNodesChange = useCallback((changes) => { if(!changes.some(change=>['position','remove'].includes(change.type)))return;setGraph((current) => { if (!current) return current; const flowNodes = current.nodes.map((node) => ({ id: node.id, position: { x: node.x, y: node.y }, selected: selection.nodes.some((selected) => selected.id === node.id) })); const changed = applyNodeChanges(changes, flowNodes); return { ...current, nodes: current.nodes.map((node) => { const found = changed.find((item) => item.id === node.id); return found ? { ...node, x: found.position.x, y: found.position.y } : node; }).filter((node) => !changes.some((change) => change.type === 'remove' && change.id === node.id)), edges: current.edges.filter((edge) => !changes.some((change) => change.type === 'remove' && (change.id === edge.source_id || change.id === edge.target_id))) }; }); }, [selection]);
  const onEdgesChange = useCallback((changes) => { if(!changes.some(change=>change.type==='remove'))return;setGraph((current) => { const flowEdges = current.edges.map((edge) => ({ id: edge.id, source: edge.source_id, target: edge.target_id, selected: selection.edges.some((selected) => selected.id === edge.id) })); const changed = applyEdgeChanges(changes, flowEdges); return { ...current, edges: current.edges.filter((edge) => changed.some((item) => item.id === edge.id)) }; }); }, [selection]);
  const onConnect = useCallback((connection) => { if (!connection.source || !connection.target || connection.source === connection.target) return; try { mutate((current) => { if (connectKind === 'hierarchy' && current.edges.some((edge) => edge.kind === 'hierarchy' && edge.target_id === connection.target)) throw new Error('That node already has a hierarchy parent. Use a relation connection instead.'); const candidate = { id: uid(), source_id: connection.source, target_id: connection.target, kind: connectKind, label: '', directed: connectKind === 'hierarchy' }; if (connectKind === 'hierarchy') { const children = {}; current.edges.filter((edge) => edge.kind === 'hierarchy').forEach((edge) => (children[edge.source_id] ||= []).push(edge.target_id)); const reaches = (id) => id === connection.source || (children[id] || []).some(reaches); if (reaches(connection.target)) throw new Error('Hierarchy connections cannot make a cycle.'); } return { ...current, edges: [...current.edges, candidate] }; }); } catch (e) { setError(e.message); } }, [connectKind, mutate]);
  const applyLayout = (mode) => { if (mode === 'freeform') return mutate((current) => ({ ...current, layout_mode: 'freeform' })); mutate((current) => ({ ...Layout({ ...current, layout_mode: mode }, mode), layout_mode: mode })); setTimeout(() => flow?.fitView({ padding: .2, duration: 250 }), 0); };
  const find = () => { const term = search.trim().toLowerCase(); const target = graph.nodes.find((node) => `${node.title} ${node.description} ${node.metadata?.url || ''}`.toLowerCase().includes(term)); if (!target) return; const parents = {}; graph.edges.filter((edge) => edge.kind === 'hierarchy').forEach((edge) => parents[edge.target_id] = edge.source_id); const path = new Set([target.id]); let cursor = target.id; while (parents[cursor]) { cursor = parents[cursor]; path.add(cursor); } setRevealed(path); flow?.setCenter(target.x + target.width / 2, target.y + target.height / 2, { zoom: 1.15, duration: 250 }); };
  const exportMap = (kind) => { const svg = exportSvg(graph); if (kind === 'svg') return download(`${graph.name || 'mind-map'}.svg`, svg, 'image/svg+xml'); const image = new Image(); const blob = new Blob([svg], { type: 'image/svg+xml' }); const url = URL.createObjectURL(blob); image.onload = () => { const canvas = document.createElement('canvas'); canvas.width = image.width * 2; canvas.height = image.height * 2; canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height); canvas.toBlob((png) => { download(`${graph.name || 'mind-map'}.png`, png, 'image/png'); URL.revokeObjectURL(url); }); }; image.src = url; };
  const saveSettings = async (next) => { setSettings(next); try { await api('/settings', { method: 'PUT', body: JSON.stringify(next) }); } catch (e) { setError(e.message); } };
  if (!graph) return <main className="mind-loading">{error || 'Loading mind map…'}</main>;
  const visible = toFlow(graph, search, toggleCollapse, revealed); const selectedId = selection.nodes[0]?.id; const selectedNode = graph.nodes.find((node) => node.id === selectedId); const selectedEdge = selection.edges[0] && graph.edges.find((edge) => edge.id === selection.edges[0].id);
  return <main className="mind-editor" onClick={() => context && setContext(null)}><header className="editor-toolbar"><a className="back-link" href="/tools/mindmaps?library=1">← Maps</a><input className="map-name" value={graph.name} onChange={(event) => mutate((current) => ({ ...current, name: event.target.value }))} aria-label="Map name" /><span role="status" aria-live="polite" className={`save-status ${status === 'Offline' ? 'offline' : ''}`}>{status}</span><div className="tool-actions">{mapId==='new'?<button className="primary" disabled={publishing} onClick={publish}>Save new map</button>:null}<button onClick={undo} disabled={!history.current.past.length}>Undo</button><button onClick={redo} disabled={!history.current.future.length}>Redo</button><details className="workspace-more"><summary>More</summary><div><button onClick={() => applyLayout('mindmap')}>Arrange tree</button><button onClick={() => applyLayout('radial')}>Arrange radial</button><button onClick={() => applyLayout('freeform')}>Freeform</button><button onClick={() => exportMap('svg')}>SVG</button><button onClick={() => exportMap('png')}>PNG</button><button onClick={() => setSettingsOpen(!settingsOpen)}>Settings</button></div></details></div></header>{error ? <div className="editor-error">{error}<button onClick={() => setError('')}>×</button></div> : null}<div className="editor-body"><aside className="detail-panel"><div className="search-box"><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && find()} placeholder="Search this map…" /><button onClick={find}>Find</button></div><div className="connection-mode"><span>Draw</span><button className={connectKind === 'hierarchy' ? 'selected' : ''} onClick={() => setConnectKind('hierarchy')}>Hierarchy</button><button className={connectKind === 'relation' ? 'selected' : ''} onClick={() => setConnectKind('relation')}>Relation</button></div>{selectedNode ? <NodeDetail node={selectedNode} graph={graph} updateNode={updateNode} deleteNode={removeSelection} /> : selectedEdge ? <EdgeDetail edge={selectedEdge} update={(changes) => mutate((current) => ({ ...current, edges: current.edges.map((edge) => edge.id === selectedEdge.id ? { ...edge, ...changes } : edge) }))} remove={removeSelection} /> : <div className="panel-empty"><h2>Start mapping</h2><p>Select a node for its details. Press <kbd>Tab</kbd> to create a child or double-click the canvas for a new idea. Escape returns keyboard focus to the toolbar.</p><button className="primary" onClick={() => addNode()}>Add node</button></div>}{settingsOpen ? <SettingsPanel settings={settings} save={saveSettings} close={() => setSettingsOpen(false)} /> : null}</aside><section className="canvas" tabIndex={0} aria-label="Mind map canvas" onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();document.querySelector('.back-link')?.focus();}}}><ReactFlowProvider><ReactFlow nodes={visible.nodes} edges={visible.edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onInit={setFlow} onSelectionChange={setSelection} onNodeDragStart={() => { dragStart.current = structuredClone(graphRef.current); }} onNodeDragStop={() => { if (dragStart.current) { history.current.past.push(dragStart.current); if (history.current.past.length > 100) history.current.past.shift(); history.current.future = []; dragStart.current = null; } }} onNodeDoubleClick={(_, node) => setSelection({ nodes: [node], edges: [] })} onNodeContextMenu={(event, node) => { event.preventDefault(); setContext({ x: event.clientX, y: event.clientY, node }); }} onPaneDoubleClick={(event) => { const point = flow?.screenToFlowPosition({ x: event.clientX, y: event.clientY }); addNode(null, point); }} fitView snapToGrid={settings.snap} snapGrid={[20, 20]} deleteKeyCode={null} panOnScroll><Background gap={20} size={1} color="#514861" style={{ opacity: settings.grid ? 1 : 0 }} /><Controls showInteractive={false} />{settings.minimap ? <MiniMap nodeColor={(node) => node.data?.style_override?.accent || '#a875ff'} /> : null}</ReactFlow></ReactFlowProvider></section></div>{context ? <div className="node-menu" style={{ left: context.x, top: context.y }} onClick={(event) => event.stopPropagation()}><button onClick={() => { addNode(context.node.id); setContext(null); }}>Add child</button><button onClick={() => { setSelection({ nodes: [context.node], edges: [] }); addSibling(); setContext(null); }}>Add sibling</button><button onClick={() => { toggleCollapse(context.node.id); setContext(null); }}>{context.node.data.collapsed ? 'Expand branch' : 'Collapse branch'}</button><button className="danger-link" onClick={() => { setSelection({ nodes: [context.node], edges: [] }); removeSelection(); setContext(null); }}>Delete node</button></div> : null}</main>;
}

function NodeDetail({ node, updateNode, deleteNode }) { const metadata = node.metadata || {}; return <div className="node-detail"><p className="eyebrow">NODE DETAILS</p><label>Title<input className="detail-title" value={node.title} onChange={(event) => updateNode(node.id, { title: event.target.value })} /></label><label>Type<select value={node.type} onChange={(event) => updateNode(node.id, { type: event.target.value })}>{types.map((type) => <option key={type} value={type}>{typeLabels[type]}</option>)}</select></label><label>Notes<textarea value={node.description} onChange={(event) => updateNode(node.id, { description: event.target.value })} placeholder="A little context, not a whole document." /></label><label>Link<input value={metadata.url || ''} placeholder="https://…" onChange={(event) => updateNode(node.id, { metadata: { ...metadata, url: event.target.value } })} /></label><label>Accent color<input type="color" value={node.style_override?.accent || '#a875ff'} onChange={(event) => updateNode(node.id, { style_override: { ...node.style_override, accent: event.target.value } })} /></label><button className="danger-button" onClick={deleteNode}>Delete node</button></div>; }

function EdgeDetail({ edge, update, remove }) { return <div className="node-detail"><p className="eyebrow">CONNECTION</p><label>Kind<select value={edge.kind} onChange={(event) => update({ kind: event.target.value, directed: event.target.value === 'hierarchy' ? true : edge.directed })}><option value="hierarchy">Hierarchy</option><option value="relation">Relation</option></select></label><label>Label<input value={edge.label} onChange={(event) => update({ label: event.target.value })} placeholder="Optional label" /></label>{edge.kind === 'relation' ? <label className="check-label"><input type="checkbox" checked={edge.directed} onChange={(event) => update({ directed: event.target.checked })} /> Directional</label> : null}<button className="danger-button" onClick={remove}>Delete connection</button></div>; }

function SettingsPanel({ settings, save, close }) { const set = (key, value) => save({ ...settings, [key]: value }); return <div className="settings-panel"><div><p className="eyebrow">MIND MAP SETTINGS</p><button onClick={close}>×</button></div><label>Default layout<select value={settings.default_layout || 'freeform'} onChange={(event) => set('default_layout', event.target.value)}><option value="freeform">Freeform</option><option value="mindmap">Mind map</option><option value="radial">Radial</option></select></label><label>Default node type<select value={settings.default_node_type || 'idea'} onChange={(event) => set('default_node_type', event.target.value)}>{types.map((type) => <option key={type} value={type}>{typeLabels[type]}</option>)}</select></label>{[['minimap', 'Show minimap'], ['grid', 'Show grid'], ['snap', 'Snap to grid']].map(([key, label]) => <label className="check-label" key={key}><input type="checkbox" checked={Boolean(settings[key])} onChange={(event) => set(key, event.target.checked)} /> {label}</label>)}</div>; }

function App() { return document.getElementById('mindmap-root').dataset.page === 'library' ? <Library /> : <Editor />; }
createRoot(document.getElementById('mindmap-root')).render(<App />);
