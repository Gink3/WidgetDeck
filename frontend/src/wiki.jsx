import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import katex from "katex";
import "katex/dist/katex.min.css";
import { equationAt } from "./wiki-math.mjs";
import {
  newId,
  syncInfobox,
  articleHeadings,
  headingLabel,
  resolvePage,
  wikiTokens,
  slugify,
  infobox,
  templates,
  builtins,
  expandMacro,
  continueList,
  completionAt,
  editable,
  normalizeInfoboxTable,
  normalizeTaskLists,
  infoboxFacts,
} from "./wiki-utils.mjs";
import "./wiki.css";
import "./wiki-links.css";
import "./wiki-pkm.css";
import { API, api } from "./wiki-api.mjs";
import {
  PageLink,
  TopicSettings,
  TopicList,
  ConnectionSuggestions,
  Attachments,
  UnavailablePage,
} from "./wiki-features.jsx";
import { SectionTree, BackupManager } from "./wiki-reading.jsx";
import { figureBlocks, figureTemplate } from "./wiki-figures.mjs";
import { EditorToolbar } from "./wiki-toolbar.jsx";
import { formatTableAt, editTableAt } from "./wiki-tables.mjs";
import { WikiGraph } from "./wiki-graph.jsx";
import { Inbox } from "./wiki-inbox.jsx";
import { storeDraft, recoverableDrafts } from "./wiki-drafts.mjs";
const emptyMetadata = {
  type: "Article",
  status: "draft",
  categories: [],
  properties: {},
  sources: [],
};
function useMacros() {
  const [custom, setCustom] = useState([]);
  const [error, setError] = useState("");
  const reload = () =>
    api("/macros")
      .then((r) => setCustom(r.macros))
      .catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);
  return {
    macros: [
      ...custom,
      ...builtins.filter((b) => !custom.some((m) => m.name === b.name)),
    ],
    custom,
    reload,
    error,
  };
}
function MacroManager({ state }) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");
  async function save() {
    try {
      await api("/macros/" + encodeURIComponent(name), {
        method: "PUT",
        body: JSON.stringify({ content }),
      });
      state.reload();
      setMessage("Macro saved.");
    } catch (e) {
      setMessage(e.message);
    }
  }
  return (
    <details className="wiki-panel">
      <summary>Define macros and templates</summary>
      <p>
        Type <code>:::name</code> on its own line and press Enter to insert a
        template. Macros insert text once; editing a macro does not change
        existing pages.
      </p>
      <label>
        Existing macro
        <select
          value=""
          onChange={(e) => {
            const m = state.macros.find((m) => m.name === e.target.value);
            setName(m.name);
            setContent(m.content);
          }}
        >
          <option value="">Choose to edit…</option>
          {state.macros.map((m) => (
            <option key={m.name}>{m.name}</option>
          ))}
        </select>
      </label>
      <label>
        Macro name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="meeting"
        />
      </label>
      <label>
        Template text
        <textarea
          rows="8"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </label>
      <button onClick={save}>Save macro</button>{" "}
      <button
        disabled={!state.custom.some((m) => m.name === name)}
        onClick={async () => {
          try {
            await api("/macros/" + encodeURIComponent(name), {
              method: "DELETE",
            });
            state.reload();
            setMessage(
              "Custom macro removed; built-in default restored if available.",
            );
          } catch (e) {
            setMessage(e.message);
          }
        }}
      >
        Remove custom macro
      </button>
      <p role="status">{message || state.error}</p>
    </details>
  );
}
function Markdown({ content, pages, counts = {}, navigation = true }) {
  const parts = figureBlocks(content);
  if (parts.some(part => part.type === "figure")) return <>{parts.map((part, index) => part.type === "figure" ? (
    <figure className="wiki-figure wiki-figure-right" key={index}>
      <Markdown content={part.image} pages={pages} navigation={false} />
      {part.caption && <figcaption><Markdown content={part.caption} pages={pages} navigation={false} /></figcaption>}
    </figure>
  ) : <Markdown key={index} content={part.content} pages={pages} counts={counts} navigation={navigation} />)}</>;

  const text = normalizeTaskLists(content)
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, target, label) => {
      const clean = target.trim().replace(/\\$/, "");
      const page = pages.find(
        (p) =>
          p.slug === clean ||
          [p.title, ...(p.aliases || [])].some(
            (v) => v.toLowerCase() === clean.toLowerCase(),
          ),
      );
      return `[${label || clean}](/tools/wiki/${encodeURIComponent(page?.slug || slugify(clean))})`;
    })
    .replace(/\[@([\w-]+)\]/g, (_, id) => `[↗ ${id}](#source-${id})`);
  const headings = Object.fromEntries(
    [1, 2, 3, 4, 5, 6].map((level) => [
      "h" + level,
      ({ children }) => {
        const textOf = (values) =>
          React.Children.toArray(values)
            .map((c) =>
              typeof c === "string" || typeof c === "number"
                ? String(c)
                : textOf(c.props?.children),
            )
            .join("");
        const plain = headingLabel(textOf(children));
        const base = slugify(plain);
        const n = counts[base] || 0;
        counts[base] = n + 1;
        const id = base + (n ? "-" + n : "");
        return React.createElement(
          "h" + level,
          {
            id: navigation ? id : undefined,
            "data-wiki-heading": navigation ? true : undefined,
          },
          <a className="section-anchor" href={"#" + id}>
            {children}
          </a>,
        );
      },
    ]),
  );
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeRaw, rehypeSanitize, [rehypeKatex, { trust: false, strict: "ignore" }]]}
      components={{
        ...headings,
        a: ({ href, children }) => (
          <PageLink href={href} pages={pages}>
            {children}
          </PageLink>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
function InfoBox({ content, pages, properties }) {
  content = normalizeInfoboxTable(content);
  const facts = { ...infoboxFacts(content), ...properties };
  const escape = (value) =>
    String(value).replace(/\|/g, "\\|").replace(/\n/g, "<br>");
  const table =
    "| Detail | Value |\n| --- | --- |" +
    Object.entries(facts)
      .map(([k, v]) => `\n| ${escape(k)} | ${escape(v)} |`)
      .join("");
  content = content.replace(
    /^\|[^\n]*\|\s*\n\|[ :|\-]+\|[^\S\n]*(?:\n\|[^\n]*\|[^\S\n]*)*/m,
    () => table,
  );
  return (
    <aside className="wiki-infobox">
      <Markdown
        content={content
          .replace(/^:::infobox[^\S\n]*\n/, "")
          .replace(/\n:::\n?$/, "")}
        pages={pages}
        navigation={false}
      />
    </aside>
  );
}
function EquationPreview({ equation }) {
  if (!equation) return null;
  let html, error;
  try {
    html = katex.renderToString(equation.source, {
      displayMode: equation.display, throwOnError: true, trust: false, strict: "ignore",
    });
  } catch (e) {
    error = e.message.replace(/^KaTeX parse error:\s*/, "");
  }
  return <aside className="wiki-equation-preview" aria-label="Live equation preview">
    <strong>Equation preview</strong>
    {error ? <p role="status">Check equation syntax: {error}</p> :
      <div dangerouslySetInnerHTML={{ __html: html }} />}
  </aside>;
}
function Preview({ page, pages }) {
  const tokens = wikiTokens(page.content);
  const targets = [
    ...new Map(
      tokens
        .map((t) => resolvePage(t.target, pages))
        .filter(Boolean)
        .map((p) => [p.id, p]),
    ).values(),
  ];
  const outgoing = targets.filter((p) => !p.deleted_at && p.id !== page.id);
  const deleted = targets.filter((p) => p.deleted_at);
  const missing = [
    ...new Set(
      tokens
        .filter((t) => !resolvePage(t.target, pages))
        .map((t) => slugify(t.target)),
    ),
  ];
  const meta = { ...emptyMetadata, ...page.metadata };
  const blocks = page.content.split(
    /(:::infobox[^\S\n]*\n[\s\S]*?\n:::(?:\n|$))/g,
  );
  const headings = articleHeadings(page.content);
  const headingCounts = {};
  const primaryInfobox = blocks.findIndex((block) =>
    /^:::infobox[^\S\n]*\n/.test(block),
  );
  return (
    <div className="wiki-reading-layout">
      <SectionTree headings={headings} />
      <article className="markdown-preview" id="article-top">
        <h1>{page.title}</h1>
        {primaryInfobox >= 0 && (
          <InfoBox
            content={blocks[primaryInfobox]}
            pages={pages}
            properties={meta.properties}
          />
        )}
        {blocks.map((block, i) =>
          i === primaryInfobox ? null : /^:::infobox[^\S\n]*\n/.test(block) ? (
            <InfoBox
              key={i}
              content={block}
              pages={pages}
              properties={meta.properties}
            />
          ) : (
            <Markdown
              key={i}
              content={block}
              pages={pages}
              counts={headingCounts}
            />
          ),
        )}
        <TopicList page={page} pages={pages} />
        {primaryInfobox < 0 && Object.keys(meta.properties).length > 0 && (
          <section className="wiki-properties">
            <h2>Properties</h2>
            <dl>
              {Object.entries(meta.properties).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </React.Fragment>
              ))}
            </dl>
          </section>
        )}
        {meta.sources.length > 0 && (
          <section className="wiki-references">
            <h2>References</h2>
            <ol>
              {meta.sources.map((s) => (
                <li key={s.id} id={"source-" + s.id}>
                  <strong>{s.title}</strong>
                  {s.url && /^https?:\/\//i.test(s.url) && (
                    <>
                      {" "}
                      —{" "}
                      <a href={s.url} target="_blank" rel="noreferrer">
                        Source
                      </a>
                    </>
                  )}
                  {s.locator && <> · {s.locator}</>}
                  {s.notes && <p>{s.notes}</p>}
                </li>
              ))}
            </ol>
          </section>
        )}
        <Attachments slug={page.slug} editable={false} expanded />
        <footer className="wiki-link-sections">
          {[
            ["Links from this page", outgoing],
            ["Links here", page.links?.incoming],
          ].map(([title, links]) => (
            <section key={title}>
              <h2>{title}</h2>
              {links?.length ? (
                <ul>
                  {links.map((l) => (
                    <li key={l.slug}>
                      <PageLink href={"/tools/wiki/" + l.slug} pages={pages}>
                        {l.title}
                      </PageLink>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No links yet.</p>
              )}
            </section>
          ))}
          {!!missing.length && (
            <section>
              <h2>Missing pages</h2>
              {missing.map((s) => (
                <p key={s}>
                  <PageLink href={"/tools/wiki/" + s} pages={pages}>
                    {s}
                  </PageLink>
                </p>
              ))}
            </section>
          )}
          {!!deleted.length && (
            <section>
              <h2>Pages in trash</h2>
              {deleted.map((p) => (
                <p key={p.slug}>
                  <PageLink href={"/tools/wiki/" + p.slug + "?edit=1"} pages={pages}>
                    {p.title}
                  </PageLink>
                </p>
              ))}
            </section>
          )}
        </footer>
        <p>
          Categories:{" "}
          {meta.categories.map((c) => (
            <a
              className="wiki-chip"
              key={c}
              href={"/tools/wiki?category=" + encodeURIComponent(c)}
            >
              {c}
            </a>
          ))}
        </p>
      </article>
    </div>
  );
}
function ImageLibraryCard({ image, onSaved }) {
  const [tags, setTags] = useState(image.tags.join(", ")), [busy, setBusy] = useState(false), [error, setError] = useState("");
  return <article className="wiki-image-card">
    <a href={image.url} target="_blank" rel="noreferrer"><img src={image.url} alt={image.filename} loading="lazy" /></a>
    <h3>{image.filename}</h3><p>{Math.ceil(image.byte_size / 1024)} KB · {new Date(image.created_at).toLocaleDateString()}</p>
    <form onSubmit={async e => {
      e.preventDefault(); if (busy) return; setBusy(true); setError("");
      try {
        const result = await api(`/images/${image.id}/metadata`, { method: "PATCH", body: JSON.stringify({
          tags: tags.split(",").map(value => value.trim()).filter(Boolean), revision: image.revision }) });
        setTags(result.image.tags.join(", ")); onSaved({ ...image, ...result.image });
      } catch (error) { setError(error.message); } finally { setBusy(false); }
    }}>
      <label>Tags for {image.filename}<input value={tags} disabled={busy} onChange={e => setTags(e.target.value)} placeholder="Comma-separated tags" /></label>
      <button disabled={busy}>{busy ? "Saving…" : "Save tags"}</button>
      {error && <p role="alert">{error}</p>}
    </form>
    <p>Used by {image.pages.length ? image.pages.map((page, i) => <React.Fragment key={page.slug}>{i ? ", " : ""}<a href={`/tools/wiki/${page.slug}`}>{page.title}</a></React.Fragment>) : "no active pages"}</p>
  </article>;
}

function ImageLibrary({ onClose }) {
  const dialog = useRef(null), sequence = useRef(0);
  const [query, setQuery] = useState(""), [images, setImages] = useState([]), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  useEffect(() => { dialog.current.showModal(); }, []);
  useEffect(() => {
    const request = ++sequence.current; setLoading(true);
    const timer = setTimeout(() => api('/images?'+new URLSearchParams({ q: query }))
      .then(result => { if (request === sequence.current) { setImages(result.images); setError(""); } })
      .catch(error => { if (request === sequence.current) setError(error.message); })
      .finally(() => { if (request === sequence.current) setLoading(false); }), 180);
    return () => { clearTimeout(timer); ++sequence.current; };
  }, [query]);
  return <dialog ref={dialog} className="wiki-image-library" aria-labelledby="wiki-image-library-title" onClose={onClose}>
    <header><h2 id="wiki-image-library-title">Image library</h2><button onClick={() => dialog.current.close()}>Close image library</button></header>
    <p>Find uploaded and imported images by filename or tags and see which pages use them.</p>
    <label>Search images<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filename or tag" /></label>
    {error && <p role="alert">{error}</p>}{loading && <p role="status">Loading images…</p>}
    {!loading && !images.length && <p>No matching images. Images uploaded or imported in Wiki appear here.</p>}
    <div className="wiki-image-grid">{images.map(image => <ImageLibraryCard key={image.id} image={image} onSaved={saved => setImages(all => all.map(entry => entry.id === saved.id ? saved : entry))} />)}</div>
  </dialog>;
}

function Library() {
  const [showImages, setShowImages] = useState(false);
  const savedHtmlDialog = useRef(null);
  const [savedHtml, setSavedHtml] = useState(null), [savedAssets, setSavedAssets] = useState([]),
    [savedSource, setSavedSource] = useState(""), [savedImporting, setSavedImporting] = useState(false),
    [savedError, setSavedError] = useState(""), [savedResult, setSavedResult] = useState(null);
  const importDialog = useRef(null);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState(null);
  const newPageDialog = useRef(null);
  useEffect(()=>{if(location.pathname.endsWith("/new")||new URLSearchParams(location.search).get("new")==="1"){newPageDialog.current.showModal();newPageDialog.current.querySelector("input")?.focus();}},[]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [navigation, setNavigation] = useState({ pinned: [], recent: [] });
  const [showMap, setShowMap] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const advancedRef = useRef(null);
  const advancedButton = useRef(null);
  useEffect(() => {
    if (!advancedOpen) return;
    const dismiss = e => {
      if (e.type === "keydown" && e.key !== "Escape") return;
      if (e.type === "pointerdown" && advancedRef.current?.contains(e.target)) return;
      setAdvancedOpen(false);
      if (e.type === "keydown") advancedButton.current?.focus();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismiss);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", dismiss); };
  }, [advancedOpen]);
  const params = new URLSearchParams(location.search);
  const [pages, setPages] = useState([]),
    [query, setQuery] = useState(""),
    [category, setCategory] = useState(params.get("category") || ""),
    [view, setView] = useState(params.get("view") || ""),
    [error, setError] = useState(""),
    [kind, setKind] = useState("Article"),
    [property, setProperty] = useState(""),
    [activity, setActivity] = useState([]);
  const macros = useMacros();
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const seq = ++sequence.current;
    try {
      const r = await api(
        "/pages?" +
          new URLSearchParams({
            q: query,
            category,
            review: view,
            trash: view === "trash" ? "1" : "0",
          }),
      );
      if (seq === sequence.current) setPages(r.pages);
      const shortcuts = await api("/navigation");
      if (seq === sequence.current) setNavigation(shortcuts);
    } catch (e) {
      setError(e.message);
    }
  }, [query, category, view]);
  useEffect(() => {
    const t = setTimeout(load, 180);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => {
    api("/activity")
      .then((r) => setActivity(r.activity))
      .catch((e) => setError(e.message));
  }, []);
  async function create(topic = false) {
    if (creating) return;
    setCreating(true);
    setCreateError("");
    try {
      const { page } = await api("/pages", {
        method: "POST",
        body: JSON.stringify({
          title: topic
              ? "New topic"
              : "Untitled page",
          content: topic
              ? "## About this topic\n\n"
              : templates[kind],
        }),
      });
      await api("/pages/" + page.slug, {
        method: "PUT",
        body: JSON.stringify({
          metadata: {
            ...emptyMetadata,
            type: kind,
            status: "draft",
            ...(topic
              ? {
                  topic: {
                    enabled: true,
                    title: "Pages in this topic",
                    sort: "title",
                  },
                }
              : {}),
          },
        }),
      });
      location.href = "/tools/wiki/" + page.slug + "?edit=1";
    } catch (e) {
      setCreateError(e.message);
      setError(e.message);
      setCreating(false);
    }
  }
  async function restoreBackup(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("backup", file);
    try {
      const r = await api("/backup", { method: "POST", body: form });
      setError(`Imported ${r.imported} pages as copies.`);
      load();
      macros.reload();
    } catch (e) {
      setError(e.message);
    }
    e.target.value = "";
  }
  return (
    <main className="wiki-library">
      {showImages && <ImageLibrary onClose={() => setShowImages(false)} />}
      <dialog ref={savedHtmlDialog} className="wiki-new-page-dialog" aria-labelledby="wiki-saved-html-title" onCancel={e => { if (savedImporting) e.preventDefault(); }}>
        <form onSubmit={async e => {
          e.preventDefault(); if (savedImporting || !savedHtml) return;
          setSavedImporting(true); setSavedError(""); setSavedResult(null);
          const form = new FormData(); form.append("html", savedHtml); form.append("source_url", savedSource);
          savedAssets.forEach(file => form.append("assets", file, file.webkitRelativePath || file.name));
          try { const result = await api("/import-html", { method: "POST", body: form }); setSavedResult(result); load(); }
          catch (error) { setSavedError(error.message); }
          finally { setSavedImporting(false); }
        }}>
          <h2 id="wiki-saved-html-title">Import saved HTML</h2>
          <p>Choose the saved page and its companion images folder. Review the imported Markdown before publishing or editing further. If images are missing, an optional source URL lets the importer try the original website.</p>
          <label>Saved HTML file<input type="file" accept=".html,.htm,text/html" required disabled={savedImporting} onChange={e => setSavedHtml(e.target.files[0] || null)} /></label>
          <label>Companion images folder (optional)<input type="file" multiple webkitdirectory="" disabled={savedImporting} onChange={e => setSavedAssets([...e.target.files])} /></label>
          <label>Original page URL (optional)<input type="url" value={savedSource} disabled={savedImporting} onChange={e => setSavedSource(e.target.value)} placeholder="https://example.com/article" /></label>
          {savedError && <p role="alert">{savedError}</p>}
          {savedResult && <div role="status"><p>Imported <a href={`/tools/wiki/${savedResult.page.slug}?edit=1`}>{savedResult.page.title}</a></p>{savedResult.warnings.map(message => <p key={message}>{message}</p>)}</div>}
          <div className="wiki-new-page-actions"><button type="button" disabled={savedImporting} onClick={() => savedHtmlDialog.current.close()}>Close</button><button type="submit" disabled={savedImporting || !savedHtml}>{savedImporting ? "Importing…" : "Import saved page"}</button></div>
        </form>
      </dialog>
      <dialog ref={newPageDialog} className="wiki-new-page-dialog" aria-labelledby="wiki-new-page-title" onCancel={e => { if (creating) e.preventDefault(); }}>
        <form onSubmit={e => { e.preventDefault(); create(); }}>
          <h2 id="wiki-new-page-title">New page</h2>
          <p>Choose a template for your new page.</p>
          <label>Page template
            <select autoFocus value={kind} disabled={creating} onChange={e => setKind(e.target.value)}>
              {Object.keys(templates).map(k => <option key={k}>{k}</option>)}
            </select>
          </label>
          {createError && <p role="alert">{createError}</p>}
          <div className="wiki-new-page-actions">
            <button type="button" disabled={creating} onClick={() => newPageDialog.current.close()}>Cancel</button>
            <button type="submit" disabled={creating}>{creating ? "Creating…" : "Create page"}</button>
          </div>
        </form>
      </dialog>
      <div className="wiki-library-heading">
        <dialog ref={importDialog} className="wiki-new-page-dialog" aria-labelledby="wiki-import-title" onCancel={e => { if (importing) e.preventDefault(); }}>
          <form onSubmit={async e => {
            e.preventDefault();
            if (importing) return;
            setImporting(true); setImportError(""); setImportResult(null);
            try {
              const result = await api("/import-url", { method: "POST", body: JSON.stringify({ url: importUrl }) });
              setImportResult(result); load();
            } catch (error) { setImportError(error.message); }
            finally { setImporting(false); }
          }}>
            <h2 id="wiki-import-title">Import web page</h2>
            <p>Save an article as Markdown with local copies of its images. Ads and navigation are filtered where possible.</p>
            <label>Web page URL<input autoFocus type="url" required value={importUrl} disabled={importing} placeholder="https://example.com/article" onChange={e => setImportUrl(e.target.value)} /></label>
            {importError && <p role="alert">{importError}</p>}
            {importResult && <div role="status"><p>Imported <a href={`/tools/wiki/${importResult.page.slug}`}>{importResult.page.title}</a></p>{importResult.warnings.map(message => <p key={message}>{message}</p>)}</div>}
            <div className="wiki-new-page-actions">
              <button type="button" disabled={importing} onClick={() => importDialog.current.close()}>Close</button>
              <button type="submit" disabled={importing}>{importing ? "Importing…" : "Import page"}</button>
            </div>
          </form>
        </dialog>
        <div>
          <h1 className="sr-only">Wiki</h1>
        </div>
        <div>
          <div className="wiki-heading-actions" ref={advancedRef}>
          <button aria-pressed={!showMap} onClick={() => setShowMap(false)}>Pages</button>
          <button aria-pressed={showMap} onClick={() => setShowMap(true)}>Link map</button>
          <button className="primary" onClick={() => { setCreateError(""); newPageDialog.current.showModal(); }}>New page</button>
          <details className="workspace-more"><summary>More</summary><div>
          <button onClick={() => { setImportError(""); setImportResult(null); importDialog.current.showModal(); }}>Import URL</button>
          <button onClick={() => { setSavedError(""); setSavedResult(null); savedHtmlDialog.current.showModal(); }}>Import HTML</button>
          <button onClick={() => setShowImages(true)}>Image library</button>
          <button disabled={creating} onClick={() => create(true)}>New topic page</button>
          <button onClick={() => window.dispatchEvent(new Event("wiki-open-inbox"))}>Inbox</button>
          <button ref={advancedButton} aria-expanded={advancedOpen} aria-controls="wiki-advanced-menu" onClick={() => setAdvancedOpen(v => !v)}>Advanced options</button></div></details>
      <section id="wiki-advanced-menu" className="wiki-advanced-menu" aria-label="Advanced options" hidden={!advancedOpen}>
      <MacroManager state={macros} />
      <BackupManager
        onRestored={() => {
          load();
          macros.reload();
        }}
      />
      <details className="wiki-panel">
        <summary>Recent activity</summary>
        {activity.map((a) => (
          <p key={a.id}>
            {a.resource_name} · {new Date(a.occurred_at).toLocaleString()}
          </p>
        ))}
      </details>
      </section>
          </div>
        </div>
      </div>
      {showMap ? <WikiGraph /> : <>
      <div className="wiki-search-controls">
        <input
          aria-label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search titles, aliases and content…"
        />
        <button aria-expanded={filtersOpen} aria-controls="wiki-library-filters" onClick={() => setFiltersOpen(v => !v)}>Filters{[category, property, view].filter(Boolean).length ? ` (${[category, property, view].filter(Boolean).length})` : ""}</button>
      </div>
      <div className="wiki-filter-chips" aria-label="Active filters">
        {[["Search", query, setQuery], ["Category", category, setCategory], ["Property", property, setProperty], ["View", view, setView]].filter(([,value]) => value).map(([label, value, clear]) => <button key={label} aria-label={`Remove ${label.toLowerCase()} filter`} onClick={() => clear("")}>{label}: {value} ×</button>)}
      </div>
      <div id="wiki-library-filters" className="wiki-filters" hidden={!filtersOpen}>
        <input
          aria-label="Category filter"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="Filter by category"
        />
        <input
          aria-label="Property filter"
          value={property}
          onChange={(e) => setProperty(e.target.value)}
          placeholder="Property filter: Status=Reading"
        />
        <select
          aria-label="Review view"
          value={view}
          onChange={(e) => setView(e.target.value)}
        >
          {[
            ["", "All pages"],
            ["inbox", "Legacy inbox pages"],
            ["unfinished", "Unfinished"],
            ["unconnected", "Unconnected"],
            ["missing", "Missing link targets"],
            ["deleted-links", "Links to pages in trash"],
            ["stale", "Not reviewed in 90 days"],
            ["trash", "Trash"],
          ].map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <p role="status">{error}</p>
      <div className="wiki-shortcuts">
        {[["Pinned pages", navigation.pinned], ["Recently viewed", navigation.recent]].map(([title, items]) => <section key={title} className="wiki-shortcut-pages"><h2>{title}</h2>{items.length ? <ul>{items.map(p => <li key={p.id}><a href={`/tools/wiki/${p.slug}?edit=1`}>{p.title}</a>{title === "Pinned pages" && <button aria-label={`Unpin ${p.title}`} onClick={async () => { try { await api(`/pages/${p.slug}/navigation`, { method: "PUT", body: JSON.stringify({ pinned: false }) }); setNavigation(await api("/navigation")); } catch(e) { setError(e.message); } }}>Unpin</button>}</li>)}</ul> : <p>{title === "Pinned pages" ? "Pin pages below to keep them handy." : "Pages you open will appear here."}</p>}</section>)}
      </div>
      <section className="wiki-page-grid">
        {pages
          .filter((p) => {
            if (!property) return true;
            const [key, ...values] = property.split("=");
            return Object.entries(p.metadata.properties || {}).some(
              ([k, v]) =>
                k.toLowerCase().includes(key.trim().toLowerCase()) &&
                (!values.length ||
                  v
                    .toLowerCase()
                    .includes(values.join("=").trim().toLowerCase())),
            );
          })
          .map((p) => (
            <article className="wiki-page-card" key={p.id}>
              <div className="wiki-card-heading">

                <a href={"/tools/wiki/" + p.slug + "?edit=1"}><h2>{p.title}</h2></a>
              {view !== "trash" && <button aria-pressed={navigation.pinned.some(n => n.id === p.id)} aria-label={`${navigation.pinned.some(n => n.id === p.id) ? "Unpin" : "Pin"} ${p.title}`} onClick={async () => { try { await api(`/pages/${p.slug}/navigation`, { method: "PUT", body: JSON.stringify({ pinned: !navigation.pinned.some(n => n.id === p.id) }) }); setNavigation(await api("/navigation")); } catch(e) { setError(e.message); } }}>{navigation.pinned.some(n => n.id === p.id) ? "Pinned ★" : "Pin ☆"}</button>}
              </div>
              <a href={"/tools/wiki/" + p.slug + "?edit=1"}>
                <small>
                  {p.metadata.status || "draft"} ·{" "}
                  {new Date(p.updated_at).toLocaleDateString()}
                </small>
              </a>
              {view === "trash" && <button
                onClick={async () => {
                  try {
                    await api("/trash/" + p.slug + "/restore", { method: "POST" });
                    load();
                  } catch (e) {
                    setError(e.message);
                  }
                }}
              >
                Restore
              </button>}
            </article>
          ))}
      </section>
      {!pages.length && <p>No pages in this view.</p>}
      </>}

    </main>
  );
}
function Properties({ page, update, pages }) {
  const meta = { ...emptyMetadata, ...page.metadata };
  const change = (changes) => update({ metadata: { ...meta, ...changes } });
  const [field, setField] = useState("");
  const [aliasText, setAliasText] = useState(page.aliases.join(", "));
  const [categoryText, setCategoryText] = useState(meta.categories.join(", "));
  const [sourceQuery, setSourceQuery] = useState("");
  useEffect(() => {
    const parse = (text) =>
      text
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    if (JSON.stringify(parse(aliasText)) !== JSON.stringify(page.aliases))
      setAliasText(page.aliases.join(", "));
    if (JSON.stringify(parse(categoryText)) !== JSON.stringify(meta.categories))
      setCategoryText(meta.categories.join(", "));
  }, [page.aliases, meta.categories]);

  const sourcePool = [
    ...new Map(
      pages.flatMap((p) => p.metadata.sources || []).map((s) => [s.id, s]),
    ).values(),
  ];
  return (
    <details className="wiki-panel">
      <summary>Properties, categories and sources</summary>
      <div className="wiki-property-grid">
        <label>
          Page type
          <select
            value={meta.type}
            onChange={(e) => change({ type: e.target.value })}
          >
            {Object.keys(templates).map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          Page status
          <select
            value={meta.status}
            onChange={(e) => change({ status: e.target.value })}
          >
            <option value="draft">Draft</option>
            <option value="inbox">Inbox</option>
            <option value="complete">Complete</option>
          </select>
        </label>
        <label>
          Categories (comma separated)
          <input
            value={categoryText}
            onChange={(e) => {
              setCategoryText(e.target.value);
              change({
                categories: e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
        <label>
          Aliases (comma separated)
          <input
            value={aliasText}
            onChange={(e) => {
              setAliasText(e.target.value);
              update({
                aliases: e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
      </div>
      <h3>Shared infobox facts</h3>
      {Object.entries(meta.properties).map(([k, v]) => (
        <label key={k}>
          {k}
          <div className="wiki-inline">
            <input
              aria-label={`Fact: ${k}`}
              value={v}
              onChange={(e) =>
                change({
                  properties: { ...meta.properties, [k]: e.target.value },
                })
              }
            />
            <button
              onClick={() => {
                const properties = { ...meta.properties };
                delete properties[k];
                change({ properties });
              }}
            >
              Remove
            </button>
          </div>
        </label>
      ))}
      <div className="wiki-inline">
        <input
          aria-label="New property name"
          value={field}
          onChange={(e) => setField(e.target.value)}
          placeholder="Property name"
        />
        <button
          onClick={() => {
            if (field.trim()) {
              change({
                properties: { ...meta.properties, [field.trim()]: "" },
              });
              setField("");
            }
          }}
        >
          Add property
        </button>
      </div>
      <p>
        These facts also appear in the infobox and drive library filters and
        topic lists. Editing a complete infobox table updates these same facts.
      </p>
      <h3>Sources</h3>
      <p>
        Record a source here, then type <code>[@</code> in the article to cite
        it.
      </p>
      <label>
        Find an existing source
        <input
          value={sourceQuery}
          onChange={(e) => setSourceQuery(e.target.value)}
          placeholder="Search sources from other pages…"
        />
      </label>
      {sourceQuery &&
        sourcePool
          .filter(
            (s) =>
              s.title.toLowerCase().includes(sourceQuery.toLowerCase()) &&
              !meta.sources.some((v) => v.id === s.id),
          )
          .slice(0, 8)
          .map((s) => (
            <button
              key={s.id}
              onClick={() => {
                change({ sources: [...meta.sources, s] });
                setSourceQuery("");
              }}
            >
              {s.title}
            </button>
          ))}
      {meta.sources.map((s, i) => (
        <fieldset key={s.id}>
          <legend>{s.id}</legend>
          {[
            ["title", "Title"],
            ["url", "URL"],
            ["locator", "Book page / section"],
            ["notes", "Commentary"],
          ].map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                value={s[key] || ""}
                onChange={(e) =>
                  change({
                    sources: meta.sources.map((v, j) =>
                      j === i ? { ...v, [key]: e.target.value } : v,
                    ),
                  })
                }
              />
            </label>
          ))}
          <button
            onClick={() =>
              change({ sources: meta.sources.filter((_, j) => j !== i) })
            }
          >
            Remove source
          </button>
        </fieldset>
      ))}
      <button
        onClick={() =>
          change({
            sources: [
              ...meta.sources,
              {
                id: "ref-" + newId().slice(0, 8),
                title: "New source",
                url: "",
                locator: "",
                notes: "",
              },
            ],
          })
        }
      >
        Add source
      </button>{" "}
      <button onClick={() => change({ reviewed_at: new Date().toISOString() })}>
        Mark reviewed today
      </button>
      {meta.reviewed_at && (
        <p>Reviewed {new Date(meta.reviewed_at).toLocaleDateString()}</p>
      )}
    </details>
  );
}
function Editor() {
  const [wordWrap, setWordWrap] = useState(() => {
    try { return localStorage.getItem("dashboard.wiki.word-wrap") !== "off"; }
    catch { return true; }
  });
  const initialSlug = document.getElementById("wiki-root").dataset.pageSlug;
  const [page, setPage] = useState(null),
    [pages, setPages] = useState([]),
    [status, setStatus] = useState("Loading…"),
    [error, setError] = useState(""),
    [mode, setMode] = useState(
      new URLSearchParams(location.search).has("edit") ? "edit" : "preview",
    );
  const [completion, setCompletion] = useState(null),
    [selected, setSelected] = useState(0),
    [historyRows, setHistoryRows] = useState(null),
    [revisionPreview, setRevisionPreview] = useState(null),
    [leaving, setLeaving] = useState(false),
    [uploading, setUploading] = useState(false),
    [unavailable, setUnavailable] = useState(null),
    [recovery, setRecovery] = useState([]),
    [localMessage, setLocalMessage] = useState("");
  const localKey = useRef(null),
    recoveredKeys = useRef([]);
  const [draftTab] = useState(() => newId());
  const uploadBusy = useRef(false);
  const returningToLibrary = useRef(false);
  const settingsDialog = useRef(null);
  const textHistory = useRef({ past: [], future: [], replay: false });
  const textarea = useRef(null),
    draft = useRef(null),
    baseline = useRef(null),
    inflight = useRef(null),
    timer = useRef(null);
  const [mathCaret, setMathCaret] = useState(null);
  const pendingCaret = useRef(null);
  useLayoutEffect(() => {
    const pending = pendingCaret.current, input = textarea.current;
    if (!pending || !input) return;
    pendingCaret.current = null;
    input.setSelectionRange(pending.at, pending.end ?? pending.at, pending.direction ?? "none");
    input.focus({ preventScroll: true });
    if (pending.viewport) {
      input.scrollTop = pending.viewport.top;
      input.scrollLeft = pending.viewport.left;
    }
  }, [page]);
  const macros = useMacros();
  const [editSession] = useState(() => newId());
  useEffect(() => {
    if (initialSlug === "new") {
      api("/pages", {
        method: "POST",
        body: JSON.stringify({ title: "Untitled page" }),
      })
        .then((r) => location.replace("/tools/wiki/" + r.page.slug + "?edit=1"))
        .catch((e) => setError(e.message));
      return;
    }
    Promise.all([api("/resolve/" + initialSlug), api("/index")])
      .then(([r, index]) => {
        if (r.state !== "active") {
          setUnavailable(r);
          return;
        }
        draft.current = baseline.current = r.page;
        setPage(r.page);
        api(`/pages/${r.page.slug}/navigation`, { method: "POST" }).catch(e => setError(e.message));
        setPages(index.pages);
        setStatus("Saved to server");
        try {
          setRecovery(recoverableDrafts(localStorage, r.page));
        } catch {
          setLocalMessage(
            "Browser storage is unavailable; unsaved changes cannot be recovered after closing.",
          );
        }
      })
      .catch((e) => setError(e.message));
  }, [initialSlug]);
  const refreshIndex = useCallback(async () => {
    setPages((await api("/index")).pages);
  }, []);
  useEffect(() => {
    const refresh = () => refreshIndex().catch((e) => setError(e.message));
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [refreshIndex]);
  const update = (changes) => {
    if (recovery.length) {
      setError("Recover or discard the saved local drafts before editing.");
      return;
    }
    if (typeof changes.content === "string" && changes.content !== draft.current.content && !textHistory.current.replay) {
      textHistory.current.past.push(draft.current.content);
      if (textHistory.current.past.length > 100) textHistory.current.past.shift();
      textHistory.current.future = [];
    }
    draft.current = syncInfobox(draft.current, changes);
    try {
      localKey.current = storeDraft(
        localStorage,
        draft.current,
        baseline.current.revision,
        draftTab,
      );
      setLocalMessage("Draft saved on this device.");
    } catch {
      setLocalMessage(
        "Browser storage is full or unavailable. Keep this tab open until the server saves your changes.",
      );
    }
    setPage(draft.current);
  };
  const save = useCallback(async () => {
    clearTimeout(timer.current);
    if (inflight.current) return inflight.current;
    if (!draft.current || !baseline.current) return false;
    const promise = (async () => {
      try {
        while (editable(draft.current) !== editable(baseline.current)) {
          const outgoing = draft.current;
          setStatus("Saving…");
          const { page: saved } = await api("/pages/" + baseline.current.slug, {
            method: "PUT",
            body: JSON.stringify({
              ...outgoing,
              revision: baseline.current.revision,
              edit_session: editSession,
            }),
          });
          baseline.current = saved;
          draft.current =
            editable(draft.current) === editable(outgoing)
              ? saved
              : {
                  ...draft.current,
                  slug: saved.slug,
                  revision: saved.revision,
                  links: saved.links,
                };
          const input = textarea.current;
          if (input && document.activeElement === input && !pendingCaret.current) {
            pendingCaret.current = { at: input.selectionStart, end: input.selectionEnd,
              direction: input.selectionDirection, viewport: { top: input.scrollTop, left: input.scrollLeft } };
          }
          setPage(draft.current);
          history.replaceState(null, "", "/tools/wiki/" + saved.slug);
        }
        setStatus("Saved to server");
        try {
          if (localKey.current) localStorage.removeItem(localKey.current);
          for (const key of recoveredKeys.current) localStorage.removeItem(key);
          recoveredKeys.current = [];
          localKey.current = null;
          setLocalMessage("");
        } catch {
          /* Server save is authoritative. */
        }
        setError("");
        return true;
      } catch (e) {
        setStatus(
          localKey.current ? "Saved locally · server unavailable" : "Unsaved",
        );
        setError(e.message);
        return false;
      }
    })();
    inflight.current = promise;
    try {
      return await promise;
    } finally {
      if (inflight.current === promise) inflight.current = null;
    }
  }, [editSession]);
  useEffect(() => {
    if (page && editable(page) !== editable(baseline.current)) {
      setStatus("Unsaved");
      timer.current = setTimeout(save, 650);
    }
    return () => clearTimeout(timer.current);
  }, [page, save]);
  useEffect(() => {
    const protect = (event) => {
      if (returningToLibrary.current) return;
      if (
        uploadBusy.current ||
        inflight.current ||
        editable(draft.current) !== editable(baseline.current)
      ) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, []);
  const moveCaret = (at, viewport = null) => {
    pendingCaret.current = { at, viewport };
  };
  const inspect = (input) => {
    setCompletion(
      completionAt(
        input.value,
        input.selectionStart,
        pages.filter((p) => !p.deleted_at),
        draft.current.metadata.sources || [],
        macros.macros,
      ),
    );
    setSelected(0);
  };
  const choose = (item) => {
    const input = textarea.current;
    const end = completion.end ?? input.selectionStart;
    let tail = page.content.slice(end);
    if (completion.kind === "page" && tail.startsWith("]]"))
      tail = tail.slice(2);
    if (completion.kind === "source" && tail.startsWith("]"))
      tail = tail.slice(1);
    update({
      content: page.content.slice(0, completion.start) + item.value + tail,
    });
    moveCaret(completion.start + (item.caret ?? item.value.length));
    setCompletion(null);
  };
  const historyStep = (direction) => {
    if (recovery.length) return;
    const source = textHistory.current[direction === "undo" ? "past" : "future"];
    const target = textHistory.current[direction === "undo" ? "future" : "past"];
    if (!source.length) return;
    target.push(draft.current.content);
    textHistory.current.replay = true;
    update({ content: source.pop() });
    textHistory.current.replay = false;
    setCompletion(null);
  };
  const keydown = (event) => {
    if ((event.ctrlKey || event.metaKey) && ["z", "y"].includes(event.key.toLowerCase())) {
      event.preventDefault(); historyStep(event.key.toLowerCase() === "y" || event.shiftKey ? "redo" : "undo"); return;
    }
    if ((event.ctrlKey || event.metaKey) && ["b", "i"].includes(event.key.toLowerCase())) {
      event.preventDefault(); const mark = event.key.toLowerCase() === "b" ? "**" : "_"; insert(mark, mark, "text"); return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      save();
      return;
    }
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      if (recovery.length) return;
      const input = event.currentTarget;
      const start = input.selectionStart, end = input.selectionEnd;
      const content = input.value;
      let next, nextStart, nextEnd;
      if (start === end && !event.shiftKey) {
        next = content.slice(0, start) + "  " + content.slice(end);
        nextStart = nextEnd = start + 2;
      } else {
        const lineStart = start === 0 ? 0 : content.lastIndexOf("\n", start - 1) + 1;
        // A selection ending at the next line's start excludes that line.
        const blockEnd = end > start && content[end - 1] === "\n" ? end - 1 : end;
        let offset = lineStart;
        const edits = content.slice(lineStart, blockEnd).split("\n").map(line => {
          const removed = event.shiftKey ? (line.match(/^(?:\t| {1,2})/)?.[0].length || 0) : 0;
          const edit = { at: offset, removed, added: event.shiftKey ? "" : "  " };
          offset += line.length + 1;
          return edit;
        });
        const adjust = position => edits.reduce((result, edit) =>
          edit.at <= position ? result + edit.added.length - Math.min(edit.removed, position - edit.at) : result, position);
        nextStart = adjust(start);
        nextEnd = adjust(end);
        next = content;
        for (const edit of edits.reverse()) {
          next = next.slice(0, edit.at) + edit.added + next.slice(edit.at + edit.removed);
        }
      }
      update({ content: next });
      setCompletion(null);
      requestAnimationFrame(() => {
        input.focus();
        input.setSelectionRange(nextStart, nextEnd);
      });
      return;
    }
    if (event.key === "Escape") {
      setCompletion(null);
      return;
    }
    if (event.key === "Enter") {
      const expanded = expandMacro(
        page.content,
        event.currentTarget.selectionStart,
        macros.macros,
      );
      if (expanded) {
        event.preventDefault();
        update({ content: expanded.content });
        moveCaret(expanded.caret);
        setCompletion(null);
        return;
      }
    }
    if (completion?.items.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setSelected(
          (n) =>
            (n +
              (event.key === "ArrowDown" ? 1 : -1) +
              completion.items.length) %
            completion.items.length,
        );
      }
      if (event.key === "Enter") {
        event.preventDefault();
        choose(completion.items[selected]);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !recovery.length) {
      const input = event.currentTarget;
      const continued = continueList(input.value, input.selectionStart, input.selectionEnd);
      if (continued) {
        event.preventDefault();
        update({ content: continued.content });
        moveCaret(continued.caret);
        setCompletion(null);
      }
    }
  };
  const insert = (before, after = "", placeholder = "", selection = null) => {
    const input = textarea.current;
    if (!input) return;
    const content = draft.current.content;
    // Async uploads must not overwrite text entered while the request was pending.
    const range = selection?.content === content ? selection : input;
    const start = range.selectionStart,
      end = range.selectionEnd;
    const viewport = { top: input.scrollTop, left: input.scrollLeft };
    const selectedText = content.slice(start, end) || placeholder;
    update({
      content:
        content.slice(0, start) +
        before +
        selectedText +
        after +
        content.slice(end),
    });
    moveCaret(start + before.length + selectedText.length, viewport);
  };
  function returnToLibrary() {
    if (uploadBusy.current) {
      setError("Wait for the document upload to finish before leaving.");
      return;
    }
    if (editable(draft.current) !== editable(baseline.current)) {
      try {
        localKey.current = storeDraft(localStorage, draft.current, baseline.current.revision, draftTab);
      } catch {
        setError("Unable to preserve this draft on this device. Save before returning to the library.");
        return;
      }
    }
    clearTimeout(timer.current);
    returningToLibrary.current = true;
    location.href = "/tools/wiki?library=1";
  }
  async function leave() {
    if (uploadBusy.current) {
      setError("Wait for the document upload to finish before leaving.");
      return;
    }
    setLeaving(true);
    if (await save()) location.href = "/tools/wiki?library=1";
    else setLeaving(false);
  }
  async function showHistory() {
    if (!(await save())) return;
    try {
      setHistoryRows((await api("/revisions/" + draft.current.slug)).revisions);
    } catch (e) {
      setError(e.message);
    }
  }
  async function restoreRevision(row) {
    if (!(await save())) return;
    try {
      const { page: saved } = await api(
        `/revisions/${draft.current.slug}/${row.id}/restore`,
        {
          method: "POST",
          body: JSON.stringify({ revision: baseline.current.revision }),
        },
      );
      draft.current = baseline.current = saved;
      setPage(saved);
      setHistoryRows(null);
      setRevisionPreview(null);
      history.replaceState(null, "", "/tools/wiki/" + saved.slug);
    } catch (e) {
      setError(e.message);
    }
  }
  if (unavailable)
    return <UnavailablePage {...unavailable} slug={initialSlug} />;
  if (!page)
    return (
      <main className="wiki-loading">{error || "Loading wiki page…"}</main>
    );
  return (
    <main className="wiki-editor">
      <header className="wiki-toolbar">
        <button onClick={returnToLibrary} disabled={uploading}>Wiki library</button>
        <button className="primary" disabled={leaving || uploading} onClick={leave}>
          {leaving ? "Saving…" : "Save"}
        </button>
        <input
          value={page.title}
          onChange={(e) => update({ title: e.target.value })}
          aria-label="Page title"
          readOnly={mode === "preview"}
        />
        <span role="status">{status}</span>
        <div>
          {["edit", "split", "preview"].map((m) => (
            <button
              key={m}
              className={mode === m ? "selected" : ""}
              onClick={() => setMode(m)}
            >
              {m === "preview" ? "Read" : m === "edit" ? "Edit" : "Split"}
            </button>
          ))}
          <details className="workspace-more"><summary>More</summary><div>
          {mode !== "preview" && <button aria-haspopup="dialog" aria-controls="wiki-page-settings-dialog" onClick={() => settingsDialog.current.showModal()}>Page settings</button>}
          <button onClick={showHistory}>History</button>
          <button
            disabled={uploading}
            onClick={async () => {
              if (!(await save())) return;
              try {
                await api("/pages/" + draft.current.slug, { method: "DELETE" });
                location.href = "/tools/wiki";
              } catch (e) {
                setError(e.message);
              }
            }}
          >
            Trash
          </button></div></details>
        </div>
      </header>
      {error && (
        <div className="wiki-message" role="alert">
          {error} <button onClick={save}>Retry save</button>
        </div>
      )}
      {historyRows && (
        <section className="wiki-history wiki-panel">
          <button
            onClick={() => {
              setHistoryRows(null);
              setRevisionPreview(null);
            }}
          >
            Close history
          </button>
          <h2>Revision history</h2>
          <p>Restoring keeps the current version in history.</p>
          {!historyRows.length && <p>No earlier versions yet.</p>}
          {historyRows.map((r) => (
            <p key={r.id}>
              <button onClick={() => setRevisionPreview(r)}>
                {new Date(r.created_at).toLocaleString()} · {r.snapshot.title}
              </button>{" "}
              <button onClick={() => restoreRevision(r)}>Restore</button>
            </p>
          ))}
          {revisionPreview && (
            <pre>
              {revisionPreview.snapshot.content}
              {"\n\nProperties: " +
                JSON.stringify(revisionPreview.snapshot.metadata, null, 2)}
            </pre>
          )}
        </section>
      )}
      <p className="wiki-local-status" role="status">
        {localMessage || "\u00a0"}
      </p>
      {!!recovery.length && (
        <section
          className="wiki-recovery"
          role="region"
          aria-label="Recover local drafts"
        >
          <h2>Unsaved drafts found on this device</h2>
          <p>
            Review the saved copy before restoring. It may differ from the
            current server version.
          </p>
          {recovery.map((item) => (
            <details key={item.key}>
              <summary>
                {new Date(item.savedAt).toLocaleString()} — {item.page.title}
                {item.baseRevision !== baseline.current.revision
                  ? " (server version has changed)"
                  : ""}
              </summary>
              <pre>{item.page.content}</pre>
              <button
                onClick={() => {
                  recoveredKeys.current.push(item.key);
                  draft.current = { ...draft.current, ...item.page };
                  setPage(draft.current);
                  setRecovery([]);
                  setMode("edit");
                  try {
                    localKey.current = storeDraft(
                      localStorage,
                      draft.current,
                      baseline.current.revision,
                      draftTab,
                    );
                    setLocalMessage("Recovered draft saved on this device.");
                  } catch {
                    setLocalMessage(
                      "Could not store another local copy; the original recovery copy is retained.",
                    );
                  }
                }}
              >
                Use recovered draft
              </button>{" "}
              <button
                onClick={() => {
                  try {
                    localStorage.removeItem(item.key);
                    setRecovery((current) =>
                      current.filter((v) => v.key !== item.key),
                    );
                  } catch {
                    setError("Could not remove the local draft.");
                  }
                }}
              >
                Discard this draft
              </button>
            </details>
          ))}
        </section>
      )}
      <div className={"wiki-workspace " + mode}>
        <section className="wiki-edit-pane">
          <dialog ref={settingsDialog} id="wiki-page-settings-dialog" className="wiki-page-settings-dialog" aria-labelledby="wiki-page-settings-title">
            <header>
              <h2 id="wiki-page-settings-title">Page settings</h2>
              <button type="button" autoFocus onClick={() => settingsDialog.current.close()}>Close</button>
            </header>
            <p className="wiki-settings-status" role="status">{status}</p>
            {error && <p role="alert">{error}</p>}
      <Attachments
        slug={page.slug}
        editable={mode !== "preview"}
        onBusy={(value) => {
          uploadBusy.current = value;
          setUploading(value);
        }}
      />
          <div className="wiki-edit-settings">
            <Properties
              key={page.id}
              page={page}
              update={update}
              pages={pages}
            />
            <TopicSettings page={page} update={update} pages={pages} />
            <ConnectionSuggestions
              page={page}
              pages={pages}
              update={update}
              refresh={refreshIndex}
            />
            <MacroManager state={macros} />
          </div>
          </dialog>
          <EditorToolbar
            insert={insert}
            wordWrap={wordWrap}
            toggleWordWrap={() => {
              const next = !wordWrap;
              setWordWrap(next);
              try { localStorage.setItem("dashboard.wiki.word-wrap", next ? "on" : "off"); }
              catch { /* Keep the toggle usable when browser storage is unavailable. */ }
            }}
            editTable={(action) => {
              const input = textarea.current;
              if (!input || recovery.length) return;
              try {
                const result = editTableAt(input.value, input.selectionStart, action);
                update({ content: result.content }); setCompletion(null);
                moveCaret(result.caret, { top: input.scrollTop, left: input.scrollLeft });
              } catch (error) { setError(error.message); input.focus(); }
            }}
            formatTable={() => {
              const input = textarea.current;
              if (!input || recovery.length) return;
              const result = formatTableAt(input.value, input.selectionStart);
              if (!result) {
                setError("Place the cursor in a Markdown table with a header separator row (| --- | --- |), then choose Format table.");
                input.focus();
                return;
              }
              update({ content: result.content });
              setCompletion(null);
              moveCaret(result.caret, { top: input.scrollTop, left: input.scrollLeft });
            }}
            macros={macros}
            undo={() => historyStep("undo")}
            redo={() => historyStep("redo")}
            canUndo={textHistory.current.past.length > 0}
            canRedo={textHistory.current.future.length > 0}
            block={(prefix) => {
              const input = textarea.current;
              if (!input) return;
              const start = page.content.lastIndexOf("\n", Math.max(0, input.selectionStart - 1)) + 1;
              const found = page.content.indexOf("\n", input.selectionEnd);
              const end = found < 0 ? page.content.length : found;
              const changed = page.content.slice(start, end).split("\n").map(line => prefix + line.replace(/^(?:#{1,6} |[-*] (?:\[[ x]\] )?|\d+\. |> )/, "")).join("\n");
              update({ content: page.content.slice(0, start) + changed + page.content.slice(end) });
              moveCaret(start + changed.length);
            }}
            uploadImage={async (e, { captioned = false } = {}) => {
                  const input = e.target,
                    file = input.files?.[0];
                  if (!file) return;
                  const editor = textarea.current;
                  const selection = editor && { content: draft.current.content, selectionStart: editor.selectionStart, selectionEnd: editor.selectionEnd };
                  const form = new FormData();
                  form.append("image", file);
                  try {
                    const { image } = await api("/images", {
                      method: "POST",
                      body: form,
                    });
                    const imageMarkdown = `![${image.filename.replace(/[\\\[\]]/g, "\\$&")}](${image.url})`;
                    const content = captioned
                      ? "\n\n" + figureTemplate.replace("![Image description](/path/to/image.jpg)", () => imageMarkdown) + "\n"
                      : imageMarkdown;
                    insert(content, "", "", selection);
                  } catch (e) {
                    setError(e.message);
                  }
                  input.value = "";
                }}
          />
          <p className="wiki-editor-hint">
            Use Insert for elements, macros, and templates. Type [[ for pages, [@ for sources, or ::: for macros. Enter inserts a
            suggestion; Escape dismisses. Tab indents; Shift+Tab unindents. Use $…$ for inline math or $$ on separate lines for display math. Type \ inside an equation for LaTeX suggestions.
          </p>
          {completion && (
            <div
              className="wiki-completions"
              role="listbox"
              id="wiki-suggestions"
              aria-label={completion.kind + " suggestions"}
            >
              {completion.items.length ? (
                completion.items.map((item, i) => (
                  <button
                    id={"suggestion-" + i}
                    role="option"
                    aria-selected={selected === i}
                    className={selected === i ? "selected" : ""}
                    key={item.value}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(item)}
                  >
                    {item.label}
                  </button>
                ))
              ) : (
                <p>
                  No matches.{" "}
                  {completion.kind === "source"
                    ? "Add a source in Properties above."
                    : "Continue typing a new name."}
                </p>
              )}
            </div>
          )}
          <EquationPreview equation={mathCaret === null ? null : equationAt(page.content, mathCaret)} />
          <textarea
            ref={textarea}
            aria-label="Article Markdown"
            wrap={wordWrap ? "soft" : "off"}
            aria-controls={completion ? "wiki-suggestions" : undefined}
            aria-activedescendant={
              completion?.items.length ? "suggestion-" + selected : undefined
            }
            value={page.content}
            onChange={(e) => {
              update({ content: e.target.value });
              inspect(e.target);
            }}
            onClick={(e) => inspect(e.target)}
            onSelect={(e) => setMathCaret(e.currentTarget.selectionStart)}
            onKeyUp={(e) => {
              if (["ArrowLeft", "ArrowRight"].includes(e.key))
                inspect(e.target);
            }}
            onKeyDown={keydown}
            spellCheck="true"
            placeholder="Start writing, or type :::infobox and press Enter…"
          />
        </section>
        <section className="wiki-preview-pane">
          <Preview page={page} pages={pages} />
        </section>
      </div>
    </main>
  );
}
createRoot(document.getElementById("wiki-root")).render(
  <><Inbox />{document.getElementById("wiki-root").dataset.page === "library" ? (
    <Library />
  ) : (
    <Editor />
  )}</>,
);
