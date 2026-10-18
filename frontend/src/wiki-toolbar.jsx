import React, { useEffect, useRef, useState } from "react";
import { templates } from "./wiki-utils.mjs";
import "./wiki-toolbar.css";

const paths = {
  bold: "M7 4h6a4 4 0 0 1 0 8H7zm0 8h7a4 4 0 0 1 0 8H7z",
  italic: "M10 4h8M6 20h8M14 4 10 20",
  strike: "M17 6c-2-3-10-3-10 2 0 2 2 3 5 4m-8 0h16m-3 4c0 5-8 5-10 2",
  link: "m10 13 4-4M8 15l-2 2a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m4 1 2-2a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0",
  bullet: "M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1",
  numbered: "M10 6h11M10 12h11M10 18h11M3 3h2v6M3 9h4M3 14c4-3 5 1 1 3l-1 3h4",
  task: "M9 6h12M9 12h12M9 18h12M2 5l2 2 3-4M2 11h4v4H2zM2 18h4",
  code: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
  image: "M3 3h18v18H3zM3 17l6-7 5 6 3-3 4 5M16 7h.01",
  table: "M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18",
  plus: "M12 4v16M4 12h16",
  chevron: "m7 10 5 5 5-5",
  quote: "M4 6h6v7H5c0 3 1 4 3 5M14 6h6v7h-5c0 3 1 4 3 5",
  undo: "m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12",
  redo: "m16 4 5 5-5 5m5-5H10a6 6 0 0 0 0 12",
};
export function EditorIcon({ name }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.plus} /></svg>;
}
export function EditorToolbar({ insert, block, formatTable, editTable, wordWrap, toggleWordWrap, macros, uploadImage, undo, redo, canUndo, canRedo }) {
  const [menu, setMenu] = useState(""), [search, setSearch] = useState("");
  const root = useRef(null), file = useRef(null);
  const imageMode = useRef("inline");
  const chooseImage = mode => { imageMode.current = mode; file.current.click(); };
  useEffect(() => {
    const close = e => { if ((e.type === "keydown" && e.key === "Escape") || (e.type === "pointerdown" && !root.current?.contains(e.target))) setMenu(""); };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, []);
  const action = fn => { fn(); setMenu(""); setSearch(""); };
  const button = (name, label, fn, disabled = false) => <button type="button" title={label} aria-label={label} disabled={disabled} onMouseDown={e => e.preventDefault()} onClick={fn}><EditorIcon name={name} /></button>;
  const entries = [
    { name: "Inline equation", group: "Math", run: () => insert("$", "$", "E = mc^2") },
    { name: "Display equation", group: "Math", run: () => insert("\n\n$$\n", "\n$$\n\n", "x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}") },
    { name: "Captioned image", group: "Elements", run: () => chooseImage("captioned") },
    { name: "Page link", group: "Wiki", run: () => insert("[[", "]]", "Page title") },
    { name: "Source citation", group: "Wiki", run: () => insert("[@", "]", "source-id") },
    { name: "Code block", group: "Elements", run: () => insert("\n```\n", "\n```\n", "code") },
    { name: "Quote", group: "Elements", run: () => block("> ") },
    { name: "Divider", group: "Elements", run: () => insert("\n\n---\n\n") },
    ...macros.macros.map(m => ({ name: m.name, group: macros.custom.some(c => c.name === m.name) ? "Custom macros / templates" : "Macros", run: () => insert("\n" + m.content + "\n") })),
    ...Object.entries(templates).map(([name, content]) => ({ name, group: "Page templates", run: () => insert("\n" + content + "\n") })),
  ];
  return <div className="wiki-format-toolbar" ref={root} role="toolbar" aria-label="Text formatting">
    <div className="wiki-format-group">{button("undo", "Undo", undo, !canUndo)}{button("redo", "Redo", redo, !canRedo)}</div>
    <div className="wiki-format-menu-anchor">
      <button type="button" className="wiki-format-text" aria-expanded={menu === "style"} onMouseDown={e => e.preventDefault()} onClick={() => setMenu(menu === "style" ? "" : "style")}>Normal text<EditorIcon name="chevron" /></button>
      {menu === "style" && <div className="wiki-format-menu" aria-label="Text styles">{[["Normal text", ""], ["Heading 1", "# "], ["Heading 2", "## "], ["Heading 3", "### "], ["Heading 4", "#### "]].map(([name, prefix]) => <button key={name} onMouseDown={e => e.preventDefault()} onClick={() => action(() => block(prefix))}>{name}</button>)}</div>}
    </div>
    <div className="wiki-format-group">{button("bold", "Bold", () => insert("**", "**", "bold text"))}{button("italic", "Italic", () => insert("_", "_", "italic text"))}{button("strike", "Strikethrough", () => insert("~~", "~~", "text"))}{button("code", "Inline code", () => insert("`", "`", "code"))}</div>
    <div className="wiki-format-group">{button("bullet", "Bulleted list", () => block("- "))}{button("numbered", "Numbered list", () => block("1. "))}{button("task", "Task list", () => block("- [ ] "))}</div>
    <div className="wiki-format-group">{button("link", "Insert link", () => insert("[", "](https://)", "Link text"))}{button("image", "Insert image", () => chooseImage("inline"))}{button("table", "Insert table", () => insert("\n\n| Column 1 | Column 2 |\n| --- | --- |\n|  |  |\n\n"))}</div>
    <div className="wiki-format-menu-anchor">
      <button type="button" className="wiki-format-text" aria-expanded={menu === "table"} onMouseDown={e => e.preventDefault()} onClick={() => setMenu(menu === "table" ? "" : "table")}>Table tools<EditorIcon name="chevron" /></button>
      {menu === "table" && <div className="wiki-format-menu" aria-label="Table tools">{[["row-before","Insert row above"],["row-after","Insert row below"],["delete-row","Delete row"],["column-before","Insert column left"],["column-after","Insert column right"],["delete-column","Delete column"]].map(([command,label]) => <button key={command} onMouseDown={e => e.preventDefault()} onClick={() => action(() => editTable(command))}>{label}</button>)}</div>}
    </div>
    <button type="button" className="wiki-format-text" title="Align the Markdown table at the cursor" onMouseDown={e => e.preventDefault()} onClick={formatTable}>Format table</button>
    <button type="button" className="wiki-format-text" aria-pressed={wordWrap} title={wordWrap ? "Turn word wrap off" : "Turn word wrap on"} onMouseDown={e => e.preventDefault()} onClick={toggleWordWrap}>Word wrap</button>
    <input ref={file} type="file" hidden accept="image/png,image/jpeg,image/gif,image/webp,image/avif" aria-label="Upload image" onChange={e => {
      const captioned = imageMode.current === "captioned";
      imageMode.current = "inline";
      uploadImage(e, { captioned });
    }} />
    <div className="wiki-format-menu-anchor">
      <button type="button" className="wiki-format-text" title="Insert elements, macros, and templates" aria-expanded={menu === "insert"} onMouseDown={e => e.preventDefault()} onClick={() => { setMenu(menu === "insert" ? "" : "insert"); setSearch(""); }}><EditorIcon name="plus" />Insert<EditorIcon name="chevron" /></button>
      {menu === "insert" && <div className="wiki-format-menu wiki-insert-menu" aria-label="Insert elements"><input autoFocus aria-label="Find an element, macro, or template" placeholder="Search elements, macros, templates…" value={search} onChange={e => setSearch(e.target.value)} />{entries.filter(e => (e.name + " " + e.group).toLowerCase().includes(search.toLowerCase())).map(e => <button key={e.group + e.name} onMouseDown={event => event.preventDefault()} onClick={() => action(e.run)}><span>{e.name}</span><small>{e.group}</small></button>)}{macros.error && <p role="alert">{macros.error}</p>}</div>}
    </div>
  </div>;
}
