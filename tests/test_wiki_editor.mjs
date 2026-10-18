import test from "node:test";
import assert from "node:assert/strict";
import {
  expandMacro,
  continueList,
  completionAt,
  builtins,
  editable,
} from "../frontend/src/wiki-utils.mjs";
test("Enter continues lists with indentation, numbering, and unchecked tasks", () => {
  for (const [text, next] of [["- One", "- "], ["  * One", "  * "], ["\t+ One", "\t+ "], ["9. One", "10. "], ["2) One", "3) "], ["  - [x] Done", "  - [ ] "]]) {
    assert.deepEqual(continueList(text, text.length), { content: text + "\n" + next, caret: text.length + 1 + next.length });
  }
});
test("Enter splits list items and replaces selected text", () => {
  assert.deepEqual(continueList("- First second", 7), { content: "- First\n-  second", caret: 10 });
  assert.deepEqual(continueList("- First second", 7, 8), { content: "- First\n- second", caret: 10 });
});
test("Enter on an empty item exits the list", () => {
  assert.deepEqual(continueList("- One\n  - [ ] ", 14), { content: "- One\n  ", caret: 8 });
});
test("ordinary text, fenced code, and positions before the marker use normal Enter", () => {
  for (const text of ["Text", "```md\n- One", "~~~\n- One"]) assert.equal(continueList(text, text.length), null);
  assert.equal(continueList("- One", 0), null);
  assert.ok(continueList("```\ncode\n```\n- One", 18));
});
test("infobox expands at the cursor while preserving surrounding text", () => {
  const text = "Introduction\n:::infobox\nMore text";
  const result = expandMacro(text, text.indexOf("\nMore"), builtins);
  assert.match(result.content, /^Introduction\n:::infobox\n### Page details\n/);
  assert.match(result.content, /\| Detail \| Value \|/);
  assert.ok(result.content.endsWith("\nMore text"));
});
test("custom macros insert literally without executing or recursive expansion", () => {
  const result = expandMacro(":::meeting", 10, [
    { name: "meeting", content: "## Agenda\n:::other" },
  ]);
  assert.equal(result.content, "## Agenda\n:::other\n");
  assert.equal(expandMacro("inline :::meeting", 17, builtins), null);
  assert.equal(expandMacro(":::unknown", 10, builtins), null);
});
test("existing infobox block opener does not expand again", () => {
  assert.equal(
    expandMacro(":::infobox\n| Field | Value |\n:::", 10, builtins),
    null,
  );
});
test("page completion matches aliases and inserts canonical target with display title", () => {
  const result = completionAt(
    "See [[Le G",
    10,
    [{ slug: "ursula", title: "Ursula K. Le Guin", aliases: ["Le Guin"] }],
    [],
    builtins,
  );
  assert.equal(result.kind, "page");
  assert.equal(result.items[0].value, "[[ursula|Ursula K. Le Guin]]");
  assert.equal(result.start, 4);
});
test("source and macro suggestions use the active token only", () => {
  assert.equal(
    completionAt(
      "Text [@bo",
      9,
      [],
      [{ id: "book", title: "A book" }],
      builtins,
    ).items[0].value,
    "[@book]",
  );
  assert.equal(
    completionAt(":::info", 7, [], [], builtins).items[0].label,
    ":::infobox",
  );
  assert.equal(completionAt("[[closed]] text", 15, [], [], builtins), null);
});
test("metadata and aliases count as edits", () => {
  const page = {
    title: "A",
    content: "B",
    metadata: { status: "draft" },
    aliases: [],
  };
  assert.notEqual(
    editable(page),
    editable({ ...page, metadata: { status: "complete" } }),
  );
  assert.notEqual(editable(page), editable({ ...page, aliases: ["Other"] }));
});

import {
  unlinkedMentions,
  wikiTokens,
  topicPages,
  resolvePage,
} from "../frontend/src/wiki-utils.mjs";
const books = [
  {
    id: "1",
    title: "Dune",
    slug: "dune",
    aliases: ["Arrakis"],
    metadata: {
      type: "Book",
      categories: ["Books"],
      properties: { Status: "Reading" },
    },
    updated_at: "2026-10-01",
  },
  {
    id: "2",
    title: "Dune Messiah",
    slug: "dune-messiah",
    aliases: [],
    metadata: {
      type: "Book",
      categories: ["Books"],
      properties: { Status: "Finished" },
    },
    updated_at: "2026-10-02",
  },
];
test("unlinked mentions respect boundaries and avoid existing links and code", () => {
  const text =
    "Dune and Arrakis. Dunes are sand. [[Dune]] [Dune](https://example.com) `Dune`\n```text\nDune\n```\nDune Messiah";
  const mentions = unlinkedMentions(text, books, "other");
  assert.deepEqual(
    mentions.map((m) => m.text),
    ["Dune", "Arrakis", "Dune Messiah"],
  );
  assert.equal(unlinkedMentions("Dune", books, "1").length, 0);
  assert.equal(
    unlinkedMentions("Dune", [{ ...books[0], deleted_at: "today" }], "other")
      .length,
    0,
  );
});
test("stale-link tokens preserve display labels and skip code", () => {
  const tokens = wikiTokens(
    "[[Old name|Label]] `[[Old name]]`\n```\n[[Old name]]\n```",
  );
  assert.equal(tokens.length, 1);
  assert.equal(tokens[0].label, "Label");
  assert.equal(resolvePage("Arrakis", books).slug, "dune");
});
test("topic lists react to properties, exclude self and trash, and sort", () => {
  const topic = {
    enabled: true,
    category: "books",
    type: "Book",
    property: "Status",
    value: "Reading",
  };
  assert.deepEqual(
    topicPages(books, topic, "topic").map((p) => p.id),
    ["1"],
  );
  assert.equal(topicPages(books, topic, "1").length, 0);
  assert.equal(
    topicPages([{ ...books[0], deleted_at: "today" }], topic, "topic").length,
    0,
  );
  assert.equal(
    topicPages(
      [
        {
          ...books[0],
          metadata: {
            ...books[0].metadata,
            properties: { Status: "Finished" },
          },
        },
      ],
      topic,
      "topic",
    ).length,
    0,
  );
  assert.deepEqual(
    topicPages(books, { sort: "updated" }, "topic").map((p) => p.id),
    ["2", "1"],
  );
});

import { syncInfobox, articleHeadings } from "../frontend/src/wiki-utils.mjs";
import { storeDraft, recoverableDrafts } from "../frontend/src/wiki-drafts.mjs";
test("local recovery is owner scoped and preserves draft conflicts", () => {
  const records = new Map();
  const storage = {
    setItem: (k, v) => records.set(k, v),
    getItem: (k) => records.get(k),
    key: (i) => [...records.keys()][i],
    get length() {
      return records.size;
    },
  };
  const base = {
    id: "page",
    user_id: 1,
    revision: 2,
    title: "Notes",
    content: "Server",
    metadata: { properties: {} },
    aliases: [],
  };
  storeDraft(storage, { ...base, content: "Unsaved words" }, 2, "tab1");
  assert.equal(
    recoverableDrafts(storage, base)[0].page.content,
    "Unsaved words",
  );
  assert.equal(recoverableDrafts(storage, { ...base, user_id: 2 }).length, 0);
  assert.equal(
    recoverableDrafts(storage, { ...base, revision: 3 })[0].baseRevision,
    2,
  );
  assert.equal(
    recoverableDrafts(storage, { ...base, content: "Unsaved words" }).length,
    0,
  );
});
test("shared facts update Markdown and Markdown edits update facts", () => {
  const base = {
    content:
      ":::infobox\n| Detail | Value |\n| --- | --- |\n| Author | First |\n:::",
    metadata: { properties: { Author: "First" } },
  };
  const changed = syncInfobox(base, {
    metadata: { properties: { Author: "Second" } },
  });
  assert.match(changed.content, /Author \| Second/);
  assert.equal(
    syncInfobox(changed, {
      content: changed.content.replace("Second", "Third"),
    }).metadata.properties.Author,
    "Third",
  );
});
test("section tree handles nested duplicate headings, setext and fenced code", () => {
  const content =
    "## Overview\n### **Details**\n## Overview\n```\n# Ignore\n```\n:::infobox\n### Ignore too\n:::\nConclusion\n---";
  assert.deepEqual(
    articleHeadings(content).map((h) => [h.id, h.level]),
    [
      ["overview", 2],
      ["details", 3],
      ["overview-1", 2],
      ["conclusion", 2],
    ],
  );
});


test("topic selection uses stable IDs and excludes trashed pages and itself", async () => {
  const { topicPages } = await import("../frontend/src/wiki-utils.mjs");
  const pages = [{id:"a",title:"Renamed",metadata:{categories:["Books"]}}, {id:"b",title:"Other",metadata:{}}, {id:"c",title:"Deleted",deleted_at:"today"}];
  assert.deepEqual(topicPages(pages, {mode:"selected",page_ids:["a","b","c"],category:"No match"}, "b").map(p=>p.id), ["a"]);
  assert.deepEqual(topicPages(pages, {mode:"selected",page_ids:[]}, "topic"), []);
  assert.deepEqual(topicPages(pages, {mode:"filters",category:"Books"}, "topic").map(p=>p.id), ["a"]);
});

test("infobox tables without separators retain their facts and renderable structure", async () => {
  const { normalizeInfoboxTable, infoboxFacts } = await import('../frontend/src/wiki-utils.mjs');
  const content = ':::infobox\n### Article details\n\n| Detail | Value |\n| Total Levels | 2 |\n:::';
  const normalized = normalizeInfoboxTable(content);
  assert.match(normalized, /\| Detail \| Value \|\n\| --- \| --- \|\n\| Total Levels \| 2 \|/);
  assert.deepEqual(infoboxFacts(content), { 'Total Levels': '2' });
  assert.equal(normalizeInfoboxTable(normalized), normalized);
  assert.deepEqual(syncInfobox({ content: '', metadata: { properties: {} } }, { content }).metadata.properties, { 'Total Levels': '2' });
});
