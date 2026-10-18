import { editable } from "./wiki-utils.mjs";
export const draftPrefix = (page) =>
  `dashboard:wiki:draft:${page.user_id}:${page.id}:`;
export function storeDraft(storage, page, baseRevision, tabId) {
  const key = draftPrefix(page) + tabId;
  storage.setItem(
    key,
    JSON.stringify({
      page: {
        title: page.title,
        content: page.content,
        metadata: page.metadata,
        aliases: page.aliases,
      },
      baseRevision,
      savedAt: new Date().toISOString(),
    }),
  );
  return key;
}
export function recoverableDrafts(storage, page) {
  const found = [];
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (!key?.startsWith(draftPrefix(page))) continue;
    try {
      const item = JSON.parse(storage.getItem(key));
      if (
        typeof item.page?.content !== "string" ||
        typeof item.page?.title !== "string" ||
        !item.page.metadata ||
        !Array.isArray(item.page.aliases)
      )
        continue;
      if (editable(item.page) !== editable(page)) found.push({ ...item, key });
    } catch {
      /* A damaged draft must not prevent opening the article. */
    }
  }
  return found.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}
