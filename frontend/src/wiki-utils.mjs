import { figureTemplate } from "./wiki-figures.mjs";
import { mathCompletionAt } from "./wiki-math.mjs";
export function continueList(content, start, end = start) {
  const lineStart = start === 0 ? 0 : content.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = content.indexOf("\n", start);
  const stop = lineEnd < 0 ? content.length : lineEnd;
  if (end > stop) return null;
  let fence = null;
  for (const line of content.slice(0, lineStart).split("\n")) {
    const marker = line.match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (!marker) continue;
    if (!fence) fence = marker[1];
    else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
  }
  if (fence) return null;
  const match = content.slice(lineStart, stop).match(/^([\t ]*)([-+*]|\d+[.)])([\t ]+)(\[[ xX]\][\t ]+)?/);
  if (!match || start < lineStart + match[0].length) return null;
  if (!content.slice(lineStart + match[0].length, stop).trim()) {
    return { content: content.slice(0, lineStart) + match[1] + content.slice(stop), caret: lineStart + match[1].length };
  }
  const marker = /^\d/.test(match[2]) ? `${Number.parseInt(match[2], 10) + 1}${match[2].slice(-1)}` : match[2];
  const insertion = `\n${match[1]}${marker}${match[3]}${match[4] ? "[ ] " : ""}`;
  return { content: content.slice(0, start) + insertion + content.slice(end), caret: start + insertion.length };
}

// Accept checklist shorthand while keeping saved Markdown unchanged.
export function normalizeTaskLists(content) {
  let fence = null;
  return content.split("\n").map(line => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
      return line;
    }
    if (marker) {
      fence = marker[1];
      return line;
    }
    return line.replace(/^( {0,3})(\[[ xX]\])(?=\s|$)/, "$1- $2");
  }).join("\n");
}
export const slugify = (value) =>
  value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "untitled";
export const infobox =
  ":::infobox\n### Page details\n\n| Detail | Value |\n| --- | --- |\n| Type |  |\n| Status |  |\n| Related |  |\n:::\n";
export const templates = Object.fromEntries(
  Object.entries({
    Article: ["Topic", "Related"],
    Book: ["Author", "Published", "Status"],
    Person: ["Occupation", "Born", "Related"],
    Project: ["Status", "Started", "Next step"],
    Place: ["Location", "Region", "Related"],
    Concept: ["Field", "Related", "Example"],
  }).map(([name, fields]) => [
    name,
    `:::infobox\n### ${name} details\n\n| Detail | Value |\n| --- | --- |\n${fields.map((f) => `| ${f} |  |`).join("\n")}\n:::\n\n## Overview\n\n\n## Notes\n\n`,
  ]),
);
export const builtins = [
  { name: "figure", content: figureTemplate },
  { name: "infobox", content: infobox },
  ...Object.entries(templates).map(([name, content]) => ({
    name: name.toLowerCase(),
    content,
  })),
];
export function expandMacro(content, caret, macros) {
  const start = content.lastIndexOf("\n", caret - 1) + 1;
  const match = content.slice(start, caret).match(/^:::([a-z][a-z0-9_-]*)\s*$/);
  const macro = match && macros.find((m) => m.name === match[1]);
  if (!macro) return null;
  // An existing block opener should not expand again when edited.
  if (
    match[1] === "infobox" &&
    /^\n[\s\S]*?\n:::(?:\n|$)/.test(content.slice(caret))
  )
    return null;
  const replacement = macro.content.replace(/\n?$/, "\n");
  return {
    content: content.slice(0, start) + replacement + content.slice(caret),
    caret: start + replacement.indexOf("\n") + 1,
  };
}
export function completionAt(content, caret, pages, sources, macros) {
  const math = mathCompletionAt(content, caret);
  if (math) return math;
  const prefix = content.slice(0, caret);
  const page = prefix.match(/\[\[([^\]\n|]*)$/);
  const source = prefix.match(/\[@([^\]\n]*)$/);
  const macro = prefix.match(/(?:^|\n)(:::[a-z0-9_-]*)$/);
  if (page)
    return {
      start: caret - page[0].length,
      kind: "page",
      items: pages
        .filter((p) =>
          [p.title, p.slug, ...(p.aliases || [])].some((v) =>
            v.toLowerCase().includes(page[1].toLowerCase()),
          ),
        )
        .slice(0, 8)
        .map((p) => ({ label: p.title, value: `[[${p.slug}|${p.title}]]` })),
    };
  if (source)
    return {
      start: caret - source[0].length,
      kind: "source",
      items: sources
        .filter((s) =>
          (s.title + " " + s.id)
            .toLowerCase()
            .includes(source[1].toLowerCase()),
        )
        .slice(0, 8)
        .map((s) => ({ label: s.title, value: `[@${s.id}]` })),
    };
  if (macro)
    return {
      start: caret - macro[1].length,
      kind: "macro",
      items: macros
        .filter((m) => m.name.startsWith(macro[1].slice(3)))
        .slice(0, 8)
        .map((m) => ({ label: `:::${m.name}`, value: m.content })),
    };
  return null;
}
export function editable(page) {
  return JSON.stringify([
    page?.title,
    page?.content,
    page?.metadata,
    page?.aliases,
  ]);
}

// randomUUID is unavailable on HTTP LAN deployments; getRandomValues still works.
export function newId() {
  return (
    crypto.randomUUID?.() ||
    "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
      (
        Number(c) ^
        (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))
      ).toString(16),
    )
  );
}

export function resolvePage(target, pages) {
  const name = target.trim().toLowerCase();
  return (
    pages.find((p) => p.slug.toLowerCase() === name) ||
    pages.find((p) =>
      [p.title, ...(p.aliases || [])].some((v) => v.toLowerCase() === name),
    )
  );
}
// Ignore code, existing Markdown links/images, HTML and URLs when suggesting edits.
function protectedRanges(content, includeWiki = true) {
  const patterns = [
    /^([ \t]*)(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\1\2[^\n]*(?:\n|$)/gm,
    /`+[^`\n]*`+/g,
    /!?\[[^\]\n]*\]\([^\n]*?\)/g,
    /!?\[[^\]\n]+\]\[[^\]\n]*\]/g,
    /<(a|pre|code|script|style)\b[^>]*>[\s\S]*?<\/\1>|<!--[^]*?-->|<[^>]+>/gi,
    /^(?: {4}|\t).*$/gm,
    /https?:\/\/[^\s<>]+/g,
    /^\s*\[[^\]]+\]:.*$/gm,
  ];
  if (includeWiki) patterns.push(/\[\[[^\]\n]+\]\]/g);
  return patterns.flatMap((pattern) =>
    [...content.matchAll(pattern)].map((m) => [m.index, m.index + m[0].length]),
  );
}
export function wikiTokens(content) {
  const excluded = protectedRanges(content, false);
  return [...content.matchAll(/\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/g)]
    .filter(
      (m) =>
        !excluded.some(([a, b]) => m.index < b && m.index + m[0].length > a),
    )
    .map((m) => ({
      start: m.index,
      end: m.index + m[0].length,
      target: m[1].trim(),
      label: m[2] || m[1].trim(),
    }));
}
export function unlinkedMentions(content, pages, currentId) {
  const excluded = protectedRanges(content);
  const matches = [];
  const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const page of pages.filter((p) => !p.deleted_at && p.id !== currentId)) {
    for (const name of new Set([page.title, ...(page.aliases || [])])) {
      if (
        !name.trim() ||
        name.length < 2 ||
        resolvePage(name, pages)?.id !== page.id
      )
        continue;
      const regex = new RegExp(
        `(?<![\\p{L}\\p{N}_])${escape(name)}(?![\\p{L}\\p{N}_])`,
        "giu",
      );
      for (const match of content.matchAll(regex)) {
        const start = match.index,
          end = start + match[0].length;
        if (!excluded.some(([a, b]) => start < b && end > a))
          matches.push({ start, end, text: match[0], page });
      }
    }
  }
  const chosen = [];
  for (const m of matches.sort((a, b) => a.start - b.start || b.end - a.end)) {
    if (!chosen.some((c) => m.start < c.end && m.end > c.start)) chosen.push(m);
    if (chosen.length >= 30) break;
  }
  return chosen;
}
export function topicPages(pages, topic, currentId) {
  const eq = (a, b) =>
    String(a || "")
      .trim()
      .toLowerCase() ===
    String(b || "")
      .trim()
      .toLowerCase();
  return pages
    .filter((p) => {
      if (p.deleted_at || p.id === currentId) return false;
      if (topic.mode === "selected") return (topic.page_ids || []).includes(p.id);
      const meta = p.metadata || {};
      if (
        topic.category &&
        !(meta.categories || []).some((c) => eq(c, topic.category))
      )
        return false;
      if (topic.type && !eq(meta.type, topic.type)) return false;
      if (topic.status && !eq(meta.status, topic.status)) return false;
      if (
        topic.property &&
        !Object.entries(meta.properties || {}).some(
          ([k, v]) =>
            eq(k, topic.property) && (!topic.value || eq(v, topic.value)),
        )
      )
        return false;
      return true;
    })
    .sort((a, b) =>
      topic.sort === "updated"
        ? b.updated_at.localeCompare(a.updated_at)
        : a.title.localeCompare(b.title),
    );
}
export function pageExcerpt(page) {
  return (
    (page.preview || page.content || "")
      .replace(/:::infobox[^]*?\n:::/g, "")
      .replace(
        /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
        (_, target, label) => label || target,
      )
      .replace(/[#*_`|]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 300) || "No summary yet."
  );
}

export function normalizeInfoboxTable(content) {
  return content.replace(
    /^(\|[^\n]*\|)[^\S\n]*\n(?=\|)/m,
    (header, row, offset) => {
      const following = content.slice(offset + header.length).split("\n")[0];
      return /^\|[ :|\-]+\|[^\S\n]*$/.test(following)
        ? header
        : `${row}\n| --- | --- |\n`;
    },
  );
}
export function infoboxFacts(content) {
  const box = content.match(/^:::infobox[^\S\n]*\n([\s\S]*?)\n:::(?=\n|$)/m);
  const table = box && normalizeInfoboxTable(box[1]).match(
    /^\|[^\n]*\|\s*\n\|[ :|\-]+\|[^\S\n]*(?:\n\|[^\n]*\|[^\S\n]*)*/m,
  );
  const facts = {};
  if (table)
    for (const line of table[0].split("\n").slice(2)) {
      const cells = line
        .trim()
        .replace(/^\||\|$/g, "")
        .split(/(?<!\\)\|/);
      if (cells.length === 2 && cells[0].trim())
        facts[cells[0].trim().replace(/\\\|/g, "|")] = cells[1]
          .trim()
          .replace(/\\\|/g, "|");
    }
  return facts;
}
export function syncInfobox(page, changes) {
  const next = { ...page, ...changes };
  const metadata = {
    ...next.metadata,
    properties: { ...next.metadata.properties },
  };
  if ("content" in changes) {
    const before = infoboxFacts(page.content),
      after = infoboxFacts(next.content);
    // Only sync a complete block. In-progress Markdown stays untouched.
    if (/^:::infobox[^\S\n]*\n[\s\S]*?\n:::(?=\n|$)/m.test(next.content)) {
      for (const key of Object.keys(before))
        if (!(key in after)) delete metadata.properties[key];
      for (const [key, value] of Object.entries(after))
        if (
          before[key] !== value &&
          !(
            before[key] === undefined &&
            value === "" &&
            key in metadata.properties
          )
        )
          metadata.properties[key] = value;
    }
  } else if (changes.metadata?.properties) {
    const escape = (value) =>
      String(value).replace(/\|/g, "\\|").replace(/\n/g, "<br>");
    const table =
      "| Detail | Value |\n| --- | --- |" +
      Object.entries(metadata.properties)
        .map(([k, v]) => `\n| ${escape(k)} | ${escape(v)} |`)
        .join("");
    next.content = next.content.replace(
      /(^:::infobox[^\S\n]*\n)([\s\S]*?)(\n:::(?=\n|$))/m,
      (_, start, body, end) =>
        start +
        normalizeInfoboxTable(body).replace(
          /^\|[^\n]*\|\s*\n\|[ :|\-]+\|[^\S\n]*(?:\n\|[^\n]*\|[^\S\n]*)*/m,
          () => table,
        ) +
        end,
    );
  }
  return { ...next, metadata };
}
export function headingLabel(value) {
  return value
    .replace(
      /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
      (_, target, label) => label || target,
    )
    .replace(/!?\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]+>/g, "")
    .replace(/[*_`~]/g, "")
    .trim();
}
export function articleHeadings(content) {
  let fence = null,
    inBox = false;
  const counts = {},
    headings = [];
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i],
      code = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (code) {
      if (!fence) fence = code[1];
      else if (code[1][0] === fence[0] && code[1].length >= fence.length)
        fence = null;
      continue;
    }
    if (fence) continue;
    if (/^:::infobox\s*$/.test(line)) {
      inBox = true;
      continue;
    }
    if (inBox) {
      if (/^:::\s*$/.test(line)) inBox = false;
      continue;
    }
    const atx = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    const setext =
      i + 1 < lines.length &&
      line.trim() &&
      lines[i + 1].match(/^ {0,3}(=+|-+)\s*$/);
    if (!atx && !setext) continue;
    const title = headingLabel(atx ? atx[2] : line),
      level = atx ? atx[1].length : setext[1][0] === "=" ? 1 : 2;
    const base = slugify(title),
      number = counts[base] || 0;
    counts[base] = number + 1;
    headings.push({ title, level, id: base + (number ? "-" + number : "") });
    if (setext && !atx) i++;
  }
  return headings;
}
