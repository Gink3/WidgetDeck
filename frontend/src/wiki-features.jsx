import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DocumentViewer } from "./wiki-reading.jsx";
import { api, API } from "./wiki-api.mjs";
import {
  resolvePage,
  pageExcerpt,
  topicPages,
  unlinkedMentions,
  wikiTokens,
} from "./wiki-utils.mjs";

export function PageLink({ href, pages, children }) {
  const [open, setOpen] = useState(false),
    [position, setPosition] = useState({ left: 12, top: 12 });
  const host = useRef(null),
    popup = useRef(null),
    timer = useRef(null);
  let slug;
  try {
    slug =
      href?.startsWith("/tools/wiki/") && !href.startsWith("/tools/wiki/api/")
        ? decodeURIComponent(href.slice("/tools/wiki/".length).split(/[?#]/)[0])
        : null;
  } catch {
    slug = null;
  }
  const page = slug ? resolvePage(slug, pages) : null;
  const state = page ? (page.deleted_at ? "deleted" : "active") : "missing";
  const close = () => {
    clearTimeout(timer.current);
    setOpen(false);
  };
  const show = () => {
    clearTimeout(timer.current);
    const rect = host.current.getBoundingClientRect();
    setPosition({
      left: Math.max(12, Math.min(rect.left, innerWidth - 332)),
      top: Math.max(12, Math.min(rect.bottom + 8, innerHeight - 270)),
    });
    setOpen(true);
  };
  useEffect(() => {
    if (!open) return;
    const outside = (event) => {
      if (
        !host.current?.contains(event.target) &&
        !popup.current?.contains(event.target)
      )
        close();
    };
    const escape = (event) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  useEffect(() => () => clearTimeout(timer.current), []);
  if (!slug) return <a href={href}>{children}</a>;
  return (
    <span
      ref={host}
      className={"wiki-page-link " + state}
      onBlur={(event) => {
        if (
          !host.current?.contains(event.relatedTarget) &&
          !popup.current?.contains(event.relatedTarget)
        )
          close();
      }}
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") {
          clearTimeout(timer.current);
          timer.current = setTimeout(show, 250);
        }
      }}
      onPointerLeave={() => {
        timer.current = setTimeout(close, 180);
      }}
    >
      <a href={href} onFocus={show}>
        {children}
      </a>
      {state !== "active" && (
        <small> ({state === "deleted" ? "in trash" : "missing"})</small>
      )}
      <button
        type="button"
        className="wiki-preview-toggle"
        aria-label={"Preview " + (page?.title || slug)}
        aria-expanded={open}
        onClick={() => (open ? close() : show())}
      >
        ⓘ
      </button>
      {open &&
        createPortal(
          <aside
            ref={popup}
            className="wiki-hover-card"
            onBlur={(event) => {
              if (
                !host.current?.contains(event.relatedTarget) &&
                !popup.current?.contains(event.relatedTarget)
              )
                close();
            }}
            role="dialog"
            aria-label={"Page preview: " + (page?.title || slug)}
            style={position}
            onPointerEnter={() => clearTimeout(timer.current)}
            onPointerLeave={() => {
              timer.current = setTimeout(close, 180);
            }}
          >
            <button
              className="wiki-preview-close"
              aria-label="Close preview"
              onClick={close}
            >
              ×
            </button>
            <strong>{page?.title || slug}</strong>
            <p>
              {state === "deleted"
                ? "This page is in trash. Open it to restore the page and its links."
                : state === "missing"
                  ? "This page does not exist. Open the link to choose whether to create it."
                  : pageExcerpt(page)}
            </p>
            {state === "active" && (
              <small>
                {page.metadata?.type} · Updated{" "}
                {new Date(page.updated_at).toLocaleDateString()}
              </small>
            )}
            <p>
              <a href={href}>
                {state === "deleted" ? "View recovery options" : "Open page"}
              </a>
            </p>
          </aside>,
          document.body,
        )}
    </span>
  );
}

export function TopicSettings({ page, update, pages = [] }) {
  const [search, setSearch] = useState("");
  const topic = page.metadata.topic || { enabled: false, sort: "title" };
  const change = (value) =>
    update({ metadata: { ...page.metadata, topic: { ...topic, ...value } } });
  return (
    <details className="wiki-panel">
      <summary>Topic pages: selection and filters</summary>
      <label className="wiki-check">
        <input
          type="checkbox"
          checked={topic.enabled}
          onChange={(e) => change({ enabled: e.target.checked })}
        />{" "}
        Show a topic page list
      </label>
      {topic.enabled && (
        <>
          <label>Choose pages by
            <select aria-label="Choose pages by" value={topic.mode || "filters"} onChange={e => change({ mode: e.target.value })}>
              <option value="filters">Automatic filters</option>
              <option value="selected">Select individual pages</option>
            </select>
          </label>
          {topic.mode === "selected" ? <>
            <label>List heading<input value={topic.title || ""} onChange={e => change({ title: e.target.value })} /></label>
            <label>Find pages to include<input value={search} onChange={e => setSearch(e.target.value)} /></label>
            <div className="wiki-topic-picker">
              {pages.filter(p => p.id !== page.id && !p.deleted_at && p.title.toLowerCase().includes(search.toLowerCase())).map(p => <label className="wiki-check" key={p.id}>
                <input type="checkbox" checked={(topic.page_ids || []).includes(p.id)} onChange={e => change({ page_ids: e.target.checked ? [...(topic.page_ids || []), p.id] : (topic.page_ids || []).filter(id => id !== p.id) })} />{p.title}
              </label>)}
            </div>
          </> : <>
          <p>
            All filters must match. Leave a filter blank to include any value.
            This list updates as pages are added, edited, or trashed.
          </p>
          {[
            ["title", "List heading"],
            ["category", "Category"],
            ["type", "Page type"],
            ["property", "Property name"],
            ["value", "Property value"],
          ].map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                value={topic[key] || ""}
                onChange={(e) => change({ [key]: e.target.value })}
                placeholder={
                  key === "property"
                    ? "Status"
                    : key === "value"
                      ? "Reading"
                      : ""
                }
              />
            </label>
          ))}
          <label>
            Page status
            <select
              value={topic.status || ""}
              onChange={(e) => change({ status: e.target.value })}
            >
              <option value="">Any status</option>
              <option value="draft">Draft</option>
              <option value="inbox">Inbox</option>
              <option value="complete">Complete</option>
            </select>
          </label>
          </>}
          <p role="status">{topicPages(pages, topic, page.id).length} pages will appear in this topic.</p>
          <label>
            Sort by
            <select
              value={topic.sort || "title"}
              onChange={(e) => change({ sort: e.target.value })}
            >
              <option value="title">Title</option>
              <option value="updated">Recently updated</option>
            </select>
          </label>
        </>
      )}
    </details>
  );
}
export function TopicList({ page, pages }) {
  const topic = page.metadata.topic;
  if (!topic?.enabled) return null;
  const matches = topicPages(pages, topic, page.id);
  return (
    <section className="wiki-topic-list">
      <h2>{topic.title || "Pages in this topic"}</h2>
      <p>
        {matches.length} matching {matches.length === 1 ? "page" : "pages"}
      </p>
      {matches.length ? (
        <ul>
          {matches.map((p) => (
            <li key={p.id}>
              <PageLink href={"/tools/wiki/" + p.slug} pages={pages}>
                {p.title}
              </PageLink>
              <p>{pageExcerpt(p)}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          No matching pages yet. Add a page or adjust this topic’s filters in
          Edit → Page settings → Topic pages: selection and filters.
        </p>
      )}
    </section>
  );
}

export function ConnectionSuggestions({ page, pages, update, refresh }) {
  const [error, setError] = useState("");
  const mentions = useMemo(
    () => unlinkedMentions(page.content, pages, page.id),
    [page.content, pages, page.id],
  );
  const stale = wikiTokens(page.content).filter((t) => {
    const p = resolvePage(t.target, pages);
    return !p || p.deleted_at;
  });
  function replace(token, target) {
    update({
      content:
        page.content.slice(0, token.start) +
        (target ? `[[${target}|${token.label || token.text}]]` : token.label) +
        page.content.slice(token.end),
    });
  }
  return (
    <details className="wiki-panel">
      <summary>
        Connections: {mentions.length} suggested, {stale.length} stale
      </summary>
      <p role="alert">{error}</p>
      <h3>Unlinked mentions</h3>
      {!mentions.length && <p>No unlinked mentions found.</p>}
      {mentions.map((m) => (
        <div key={m.start} className="wiki-suggestion">
          <p>
            …{page.content.slice(Math.max(0, m.start - 35), m.start)}
            <mark>{m.text}</mark>
            {page.content.slice(m.end, m.end + 35)}…
          </p>
          <button onClick={() => replace(m, m.page.slug)}>
            Link to {m.page.title}
          </button>
        </div>
      ))}
      <h3>Stale links</h3>
      {!stale.length && <p>No stale wiki links.</p>}
      {stale.map((t) => {
        const target = resolvePage(t.target, pages);
        return (
          <div key={t.start} className="wiki-suggestion">
            <p>
              <strong>{t.label}</strong> —{" "}
              {target ? "page in trash" : "page missing"}
            </p>
            {target && (
              <button
                onClick={async () => {
                  try {
                    await api("/trash/" + target.slug + "/restore", {
                      method: "POST",
                    });
                    await refresh();
                  } catch (e) {
                    setError(e.message);
                  }
                }}
              >
                Restore {target.title}
              </button>
            )}
            <label>
              Replace link with
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) replace(t, e.target.value);
                }}
              >
                <option value="">Choose a page…</option>
                {pages
                  .filter((p) => !p.deleted_at)
                  .map((p) => (
                    <option key={p.id} value={p.slug}>
                      {p.title}
                    </option>
                  ))}
              </select>
            </label>
            <button onClick={() => replace(t, null)}>
              Keep text, remove link
            </button>
          </div>
        );
      })}
    </details>
  );
}

const ACCEPT =
  ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.odp,.txt,.md,.csv,.rtf,.png,.jpg,.jpeg,.gif,.webp,.avif,.heic,.heif,.tif,.tiff";
export function Attachments({ slug, editable, onBusy, expanded = false }) {
  const [viewer, setViewer] = useState(null);
  const [items, setItems] = useState([]),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api("/pages/" + slug + "/attachments")
        .then((r) => {
          if (!cancelled) setItems(r.attachments);
        })
        .catch((e) => {
          if (!cancelled) setMessage(e.message);
        });
    load();
    const interval = setInterval(load, 4000);
    return () => {
      clearInterval(interval);
      cancelled = true;
    };
  }, [slug]);
  async function upload(event) {
    const input = event.target,
      files = [...(input.files || [])];
    if (!files.length) return;
    setBusy(true);
    onBusy(true);
    const failed = [];
    let count = 0;
    try {
      for (const file of files) {
        setMessage(
          `Uploading ${count + failed.length + 1} of ${files.length}: ${file.name}`,
        );
        if (file.size > 32 * 1024 * 1024) {
          failed.push(`${file.name}: exceeds 32 MB`);
          continue;
        }
        const form = new FormData();
        form.append("document", file);
        try {
          const result = await api("/pages/" + slug + "/attachments", {
            method: "POST",
            body: form,
          });
          setItems(result.attachments);
          count++;
        } catch (e) {
          failed.push(`${file.name}: ${e.message}`);
        }
      }
    } finally {
      setMessage(
        `${count} file(s) archived.${failed.length ? " Not uploaded: " + failed.join("; ") : ""}`,
      );
      setBusy(false);
      onBusy(false);
      input.value = "";
    }
  }
  const Container = expanded ? "section" : "details";
  return (
    <Container className="wiki-panel wiki-attachments">
      {expanded ? <h2>Attachments ({items.length})</h2> : <summary>Attachments ({items.length})</summary>}
      {editable ? (
        <>
          <p>
            Archive PDFs, documents, and scanned images. Original files are
            preserved; maximum 32 MB per file.
          </p>
          <div className="wiki-upload-actions">
            <label className="wiki-upload-button">
              Upload documents
              <input
                disabled={busy}
                type="file"
                accept={ACCEPT}
                multiple
                onChange={upload}
              />
            </label>
            <label className="wiki-upload-button">
              Take a document photo
              <input
                disabled={busy}
                type="file"
                accept="image/*"
                capture="environment"
                onChange={upload}
              />
            </label>
          </div>
          <p>
            For a multi-page scan, upload a PDF exported by your phone’s
            scanning app. The photo option captures a single image.
          </p>
        </>
      ) : (
        !items.length && (
          <p>No archived files. Switch to Edit to upload documents.</p>
        )
      )}
      <p role="status" aria-live="polite">
        {message}
      </p>
      <ul>
        {items.map((a) => (
          <li key={a.id}>
            <a href={API + "/attachments/" + a.id} download>
              {a.filename}
            </a>
            <small>
              {" "}
              · {(a.byte_size / 1024 / 1024).toFixed(2)} MB ·{" "}
              {new Date(a.created_at).toLocaleDateString()}
            </small>
            <button onClick={() => setViewer(a.id)}>Preview document</button>
            <small>
              {" "}
              ·{" "}
              {a.processing_status === "ready"
                ? "Searchable"
                : a.processing_status}
            </small>
            {a.processing_error && <p>{a.processing_error}</p>}
            <details>
              <summary>File integrity</summary>
              <code>SHA-256: {a.sha256}</code>
            </details>
          </li>
        ))}
      </ul>
      {viewer && <DocumentViewer id={viewer} onClose={() => setViewer(null)} />}
    </Container>
  );
}
export function UnavailablePage({ state, slug, page }) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function recover() {
    setBusy(true);
    try {
      const result =
        state === "deleted"
          ? await api("/trash/" + page.slug + "/restore", { method: "POST" })
          : await api("/pages", {
              method: "POST",
              body: JSON.stringify({ title: slug.replace(/-/g, " "), slug }),
            });
      location.replace(
        "/tools/wiki/" +
          result.page.slug +
          (state === "missing" ? "?edit=1" : ""),
      );
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  return (
    <main className="wiki-library">
      <a href="/tools/wiki">← Wiki</a>
      <h1>{page?.title || slug}</h1>
      <p>
        {state === "deleted"
          ? "This page is in trash. Restore it to recover its content, attachments, and incoming links."
          : "This page does not exist. No empty page has been created."}
      </p>
      <button disabled={busy} onClick={recover}>
        {state === "deleted" ? "Restore page" : "Create page"}
      </button>
      <p role="alert">{error}</p>
    </main>
  );
}
