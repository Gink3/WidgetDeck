import React, { useEffect, useRef, useState } from "react";
import { api, API } from "./wiki-api.mjs";
import { DocumentViewer } from "./wiki-reading.jsx";
import "./wiki-inbox.css";

export function Inbox() {
  const [width, setWidth] = useState(390);
  const [owner, setOwner] = useState(null), [open, setOpen] = useState(false);
  const [notes, setNotes] = useState([]), [note, setNote] = useState(null);
  const [content, setContent] = useState(""), [capture, setCapture] = useState("");
  const [files, setFiles] = useState([]), [query, setQuery] = useState("");
  const [processed, setProcessed] = useState(false), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(""), [viewer, setViewer] = useState(null);
  const panel = useRef(null), text = useRef(null), captureId = useRef(null);
  const sequence = useRef(0);
  const slug = document.getElementById("wiki-root").dataset.pageSlug;
  const dirty = !!note && content !== note.content;
  const key = owner ? `wiki-inbox:${owner}` : null;
  function remember(values) {
    if (!key) return;
    try { sessionStorage.setItem(key, JSON.stringify({ ...JSON.parse(sessionStorage.getItem(key) || "{}"), ...values })); } catch { /* Server data remains available. */ }
  }
  function resize(value) {
    const next = Math.min(600, Math.max(300, value));
    setWidth(next); remember({ width: next });
  }
  useEffect(() => {
    document.body.style.setProperty("--inbox-width", `${width}px`);
    return () => document.body.style.removeProperty("--inbox-width");
  }, [width]);
  async function refresh() {
    const seq = ++sequence.current;
    const result = await api("/inbox?" + new URLSearchParams({ q: query, processed: processed ? "1" : "0" }));
    if (seq === sequence.current) setNotes(result.notes);
    return result;
  }
  useEffect(() => {
    api("/inbox").then(async result => {
      setOwner(result.owner_id);
      let saved = {};
      try { saved = JSON.parse(sessionStorage.getItem(`wiki-inbox:${result.owner_id}`) || "{}"); } catch {}
      setOpen(!!saved.open);
      if (Number.isFinite(saved.width)) setWidth(Math.min(600, Math.max(300, saved.width)));
      setCapture(saved.capture || "");
      captureId.current = saved.captureId || null;
      if (saved.id) {
        const r = await api(`/inbox/${saved.id}`);
        setNote(saved.draft?.id === r.note.id ? { ...r.note, revision: saved.draft.revision } : r.note); setContent(saved.draft?.id === r.note.id ? saved.draft.content : r.note.content);
        requestAnimationFrame(() => { if (panel.current) panel.current.scrollTop = saved.scroll || 0; });
      }
    }).catch(e => setMessage(e.message));
  }, []);
  useEffect(() => { refresh().catch(e => setMessage(e.message)); }, [query, processed]);
  useEffect(() => {
    const handler = () => { setOpen(true); remember({ open: true }); };
    window.addEventListener("wiki-open-inbox", handler);
    return () => window.removeEventListener("wiki-open-inbox", handler);
  }, [key]);
  useEffect(() => {
    document.body.classList.toggle("wiki-inbox-open", open);
    return () => document.body.classList.remove("wiki-inbox-open");
  }, [open]);
  useEffect(() => {
    const warn = e => { if (dirty || busy || files.length) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, busy, files.length]);
  async function run(action) {
    setBusy(true); setMessage("");
    try { await action(); } catch (e) { setMessage(e.message); } finally { setBusy(false); }
  }
  function select(n) {
    setNote(n); setContent(n.content); setViewer(null);
    remember({ id: n.id, scroll: 0, draft: null });
  }
  async function save(changes = {}) {
    const result = await api(`/inbox/${note.id}`, { method: "PUT", body: JSON.stringify({ revision: note.revision, content, ...changes }) });
    setNote(result.note); setContent(result.note.content); remember({ draft: null });
    await refresh();
    return result.note;
  }
  async function choose(n) {
    if (dirty) await save();
    const result = await api(`/inbox/${n.id}`);
    select(result.note);
  }
  async function submit() {
    let id = captureId.current;
    if (!id) {
      const r = await api("/inbox", { method: "POST", body: JSON.stringify({ content: capture }) });
      id = r.note.id; captureId.current = id; remember({ captureId: id });
    } else {
      const r = await api(`/inbox/${id}`);
      await api(`/inbox/${id}`, { method: "PUT", body: JSON.stringify({ revision: r.note.revision, content: capture }) });
    }
    const failed = []; const errors = [];
    for (const file of files) {
      try {
        setMessage(`Uploading ${file.name}…`);
        const form = new FormData(); form.append("document", file);
        await api(`/inbox/${id}/attachments`, { method: "POST", body: form });
      } catch (e) { failed.push(file); errors.push(`${file.name}: ${e.message}`); }
    }
    setFiles(failed);
    await refresh();
    if (failed.length) { setMessage(errors.join("\n")); return; }
    captureId.current = null; setCapture(""); remember({ capture: "", captureId: null }); setMessage("Saved to Inbox.");
  }
  const current = notes.findIndex(n => n.id === note?.id);
  return <>
    {document.getElementById("wiki-root").dataset.page !== "library" && <button className="wiki-inbox-toggle" aria-expanded={open} aria-controls="wiki-inbox" onClick={() => { setOpen(!open); remember({ open: !open }); }}>Inbox</button>}
    <div className="wiki-inbox-resize" hidden={!open} role="separator" aria-label="Resize Inbox" aria-orientation="vertical" aria-valuemin={300} aria-valuemax={600} aria-valuenow={width} tabIndex={0}
      onPointerDown={e => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => { if (e.currentTarget.hasPointerCapture(e.pointerId)) resize(window.innerWidth - e.clientX); }}
      onPointerUp={e => { if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
      onKeyDown={e => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) { e.preventDefault(); resize(e.key === "Home" ? 300 : e.key === "End" ? 600 : width + (e.key === "ArrowLeft" ? 20 : -20)); } }} />
    <aside id="wiki-inbox" className="wiki-inbox" hidden={!open} aria-label="Inbox" ref={panel} onScroll={() => remember({ scroll: panel.current.scrollTop })}>
      <header><h2>Inbox</h2><button onClick={() => { setOpen(false); remember({ open: false }); }}>Close</button></header>
      <p>Capture now. Use alongside your wiki. Process when ready.</p>
      <details open={!note}><summary>Capture a note or files</summary>
      <fieldset disabled={busy} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) setFiles([...files, ...e.dataTransfer.files]); }}>
        <legend>Quick capture</legend>
        <textarea aria-label="Capture a note" value={capture} rows={4} placeholder="A reminder, thought, or link…" onChange={e => { setCapture(e.target.value); remember({ capture: e.target.value }); }} />
        <label>Add files or drop them here<input type="file" multiple onChange={e => { const picked = [...e.target.files]; setFiles(f => [...f, ...picked]); e.target.value = ""; }} /></label>
        {files.map((f, i) => <div key={i}>{f.name} <button onClick={() => setFiles(files.filter((_, j) => i !== j))}>Remove</button></div>)}
        <button disabled={!capture.trim() && !files.length} onClick={() => run(submit)}>{captureId.current ? "Retry / finish capture" : "Save to Inbox"}</button>
      </fieldset></details>
      <p role="status" className="inbox-message">{message}</p>
      <label>Search inbox<input value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label><input type="checkbox" checked={processed} onChange={e => setProcessed(e.target.checked)} /> Show processed notes</label>
      <ul className="inbox-list">{notes.map(n => <li key={n.id}><button disabled={busy} aria-pressed={note?.id === n.id} onClick={() => run(() => choose(n))}>
        <strong>{n.content.split("\n")[0].slice(0, 100) || n.attachments[0]?.filename || "File capture"}</strong>
        <small>{new Date(n.created_at).toLocaleString()} · {n.attachments.length} files{n.processed_at ? " · Processed" : ""}</small>
      </button></li>)}</ul>
      {!notes.length && <p>{processed ? "No matching notes." : "No pending notes."}</p>}
      {note && <section aria-label="Selected note">
        <h3>{note.processed_at ? "Processed note" : "Working note"}</h3>
        <div className="inbox-actions">
          <button disabled={busy || current <= 0} onClick={() => run(() => choose(notes[current - 1]))}>Previous</button>
          <button disabled={busy || current < 0 || current >= notes.length - 1} onClick={() => run(() => choose(notes[current + 1]))}>Next</button>
        </div>
        <textarea ref={text} aria-label="Edit inbox note" value={content} rows={12} disabled={busy} onChange={e => { setContent(e.target.value); remember({ draft: { id: note.id, revision: note.revision, content: e.target.value } }); }} />
        <div className="inbox-actions">
          <button disabled={busy || !dirty} onClick={() => run(() => save())}>Save note</button>
          <button disabled={busy} onClick={() => { if (!dirty || window.confirm("Discard your unsaved edits and reload the saved note?")) run(async () => { const r = await api(`/inbox/${note.id}`); select(r.note); }); }}>Reload saved note</button>
          <button onClick={() => run(async () => { const t = text.current; await navigator.clipboard.writeText(t.selectionEnd > t.selectionStart ? content.slice(t.selectionStart, t.selectionEnd) : content); setMessage("Copied. Paste into your wiki page."); })}>Copy selection / note</button>
          {slug && slug !== "new" && <button disabled={busy} onClick={() => run(() => save({ page_slug: slug }))}>Link current page</button>}
          <button disabled={busy} onClick={() => run(async () => { const wasProcessed = note.processed_at; await save({ processed: !wasProcessed }); if (!wasProcessed && !processed) { setNote(null); setContent(""); remember({ id: null }); } })}>{note.processed_at ? "Reopen" : "Mark processed"}</button>
        </div>
        {note.pages.length > 0 && <><h4>Used on</h4>{note.pages.map(p => <p key={p.id}><a href={`/tools/wiki/${p.slug}`}>{p.title}</a>{p.deleted_at ? " (in trash)" : ""}</p>)}</>}
        {note.attachments.map(a => <div className="inbox-file" key={a.id}>
          <a href={`${API}/attachments/${a.id}`} download>{a.filename}</a>
          <button onClick={() => setViewer(a.id)}>Preview</button>
          {slug && slug !== "new" && <button disabled={busy} onClick={() => run(async () => { await api(`/inbox/${note.id}/attach/${a.id}`, { method: "POST", body: JSON.stringify({ page_slug: slug }) }); await save({ page_slug: slug }); setMessage("File attached to the current page."); })}>Attach to current page</button>}
        </div>)}
        {viewer && <DocumentViewer inline key={viewer} id={viewer} onClose={() => setViewer(null)} />}
      </section>}
    </aside>
  </>;
}
