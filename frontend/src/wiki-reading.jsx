import React, { useEffect, useState, useRef } from "react";
import { api, API } from "./wiki-api.mjs";

function nested(headings) {
  const roots = [],
    stack = [];
  for (const heading of headings) {
    const node = { ...heading, children: [] };
    while (stack.length && stack.at(-1).level >= node.level) stack.pop();
    (stack.length ? stack.at(-1).children : roots).push(node);
    stack.push(node);
  }
  return roots;
}
export function SectionTree({ headings }) {
  const [active, setActive] = useState("");
  useEffect(() => {
    let frame;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const pane = document.querySelector(".wiki-preview-pane");
        const top =
          innerWidth > 800 ? pane?.getBoundingClientRect().top || 0 : 0;
        const nodes = [...document.querySelectorAll("[data-wiki-heading]")];
        const current =
          nodes
            .filter((n) => n.getBoundingClientRect().top <= top + 100)
            .at(-1) || nodes[0];
        setActive(current?.id || "");
      });
    };
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    update();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [headings.map((h) => h.id).join("|")]);
  const list = (nodes) => (
    <ol>
      {nodes.map((h) => (
        <li key={h.id}>
          <a href={"#" + h.id} aria-current={active === h.id ? "location" : undefined}>{h.title}</a>
          {h.children.length > 0 && list(h.children)}
        </li>
      ))}
    </ol>
  );
  return (
    <nav className="wiki-section-tree" aria-label="Article sections">
      <h2>On this page</h2>
        <a href="#article-top">Top of page</a>
        {headings.length ? list(nested(headings)) : <p>No sections yet.</p>}
    </nav>
  );
}

export function DocumentViewer({ id, onClose, inline = false }) {
  const modal = useRef(null);
  const [pdfPage, setPdfPage] = useState(1);
  useEffect(() => {
    if (!inline) modal.current?.showModal();
  }, []);
  const [item, setItem] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api("/attachments/" + id + "/details")
        .then((r) => {
          if (!cancelled) setItem(r.attachment);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    load();
    const timer = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [id]);
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);
  const Container = inline ? "div" : "dialog";
  return (
    <Container
      ref={modal}
      className={inline ? "wiki-document-inline" : "wiki-document-overlay"}
      aria-label="Document preview"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <section className="wiki-document-viewer">
        <header>
          <h2>{item?.filename || "Document preview"}</h2>
          <button autoFocus onClick={onClose}>
            Close preview
          </button>
        </header>
        {error && <p role="alert">{error}</p>}
        {item && (
          <>
            <p>
              {item.processing_status === "pending" ||
              item.processing_status === "processing"
                ? "Preparing preview and searchable text…"
                : item.processing_error || "Document indexed for search."}
            </p>
            {item.preview_type === "pdf" && (
              <>
                <div className="wiki-pdf-navigation">
                  <button
                    disabled={pdfPage <= 1}
                    onClick={() => setPdfPage((value) => value - 1)}
                  >
                    Previous page
                  </button>
                  <span>
                    Page {pdfPage} of {item.preview_pages || 1}
                  </span>
                  <button
                    disabled={pdfPage >= (item.preview_pages || 1)}
                    onClick={() => setPdfPage((value) => value + 1)}
                  >
                    Next page
                  </button>
                </div>
                <img
                  className="wiki-pdf-page"
                  src={`${API}/attachments/${id}/preview?page=${pdfPage}`}
                  alt={`PDF page ${pdfPage}`}
                  onError={() =>
                    setError(
                      "Could not render this page. Download the original or retry processing.",
                    )
                  }
                />
              </>
            )}
            {item.preview_type === "image" && (
              <img
                src={`${API}/attachments/${id}/preview`}
                alt={item.filename}
              />
            )}
            <details open={item.preview_type === "text"}>
              <summary>Extracted text</summary>
              <pre>
                {item.text_content || "No text has been extracted yet."}
              </pre>
            </details>
            <a href={`${API}/attachments/${id}`} download>
              Download original
            </a>{" "}
            <button
              onClick={async () => {
                try {
                  await api("/attachments/" + id + "/process", {
                    method: "POST",
                  });
                  setItem({ ...item, processing_status: "pending" });
                } catch (e) {
                  setError(e.message);
                }
              }}
            >
              Reprocess document
            </button>
          </>
        )}
      </section>
    </Container>
  );
}

export function BackupManager({ onRestored }) {
  const [data, setData] = useState(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const dirty = useRef(false);
  const load = () =>
    api("/backups")
      .then((next) =>
        setData((current) =>
          dirty.current && current
            ? { ...next, settings: current.settings }
            : next,
        ),
      )
      .catch((e) => setMessage(e.message));
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);
  async function upload(event) {
    const input = event.target,
      file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    setMessage("Uploading backup…");
    try {
      const form = new FormData();
      form.append("backup", file);
      await api("/restores", { method: "POST", body: form });
      setMessage(
        "Restore queued. You can leave this page; progress appears below.",
      );
      load();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
      input.value = "";
    }
  }
  return (
    <details className="wiki-panel">
      <summary>Automatic backups and restore</summary>
      <p>
        Backups are verified ZIP files containing articles, history, macros,
        images, and documents. Download a copy to another device or storage
        location. Restores create copies and preserve existing pages.
      </p>
      <p role="status">{message}</p>
      {data && (
        <>
          <label className="wiki-check">
            <input
              type="checkbox"
              checked={!!data.settings.enabled}
              onChange={(e) => (
                (dirty.current = true),
                setData({
                  ...data,
                  settings: { ...data.settings, enabled: e.target.checked },
                })
              )}
            />
            Enable automatic backups
          </label>
          <label>
            Backup frequency
            <select
              value={data.settings.interval_hours}
              onChange={(e) => (
                (dirty.current = true),
                setData({
                  ...data,
                  settings: {
                    ...data.settings,
                    interval_hours: Number(e.target.value),
                  },
                })
              )}
            >
              <option value="6">Every 6 hours</option>
              <option value="24">Daily</option>
              <option value="168">Weekly</option>
            </select>
          </label>
          <label>
            Backups to retain
            <input
              type="number"
              min="1"
              max="30"
              value={data.settings.retain_count}
              onChange={(e) => (
                (dirty.current = true),
                setData({
                  ...data,
                  settings: {
                    ...data.settings,
                    retain_count: Number(e.target.value),
                  },
                })
              )}
            />
          </label>
          <button
            onClick={async () => {
              try {
                await api("/backups/settings", {
                  method: "PUT",
                  body: JSON.stringify({
                    ...data.settings,
                    enabled: !!data.settings.enabled,
                  }),
                });
                dirty.current = false;
                setMessage("Backup schedule saved.");
              } catch (e) {
                setMessage(e.message);
              }
            }}
          >
            Save backup schedule
          </button>{" "}
          <button
            onClick={async () => {
              try {
                await api("/backups/run", { method: "POST" });
                setMessage("Backup queued.");
                load();
              } catch (e) {
                setMessage(e.message);
              }
            }}
          >
            Create backup now
          </button>
          <p>
            {data.settings.last_success
              ? "Last verified backup: " +
                new Date(data.settings.last_success).toLocaleString()
              : "The first backup will run in the background."}
            {data.settings.requested ? " Backup queued." : ""}
          </p>
          {data.settings.error && <p role="alert">{data.settings.error}</p>}
          <ul>
            {data.backups.map((b) => (
              <li key={b.name}>
                <a href={API + "/backups/" + b.name}>{b.name}</a> ·{" "}
                {(b.byte_size / 1024 / 1024).toFixed(1)} MB
              </li>
            ))}
          </ul>
          <h3>Restore progress</h3>
          {data.restores.map((r) => (
            <p key={r.id}>
              {new Date(r.created_at).toLocaleString()} — {r.state}
              {r.state === "complete"
                ? `: ${r.imported} pages restored.`
                : ""}{" "}
              {r.error}
            </p>
          ))}
          {data.restores.some((r) => r.state === "complete") && (
            <button onClick={onRestored}>Refresh restored pages</button>
          )}
        </>
      )}
      <p>
        <a href={API + "/backup"}>Download a fresh export ZIP</a>
      </p>
      <label>
        Restore from exported ZIP
        <input disabled={busy} type="file" accept=".zip" onChange={upload} />
      </label>
    </details>
  );
}
