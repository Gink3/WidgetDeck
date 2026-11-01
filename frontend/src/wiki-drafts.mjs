import { editable } from "./wiki-utils.mjs";
const ownerPrefix = owner => `dashboard:wiki:draft:${owner}:`;
const retention = 7 * 86400000, recordLimit = 1024 * 1024;
function ownerKeys(storage,owner) {
  return Array.from({length:storage.length},(_,i)=>storage.key(i)).filter(key=>key?.startsWith(ownerPrefix(owner)));
}
function prune(storage,owner) {
  for (const key of ownerKeys(storage,owner)) {
    try {
      const item=JSON.parse(storage.getItem(key)), saved=Date.parse(item.savedAt);
      if (Number.isFinite(saved) && saved < Date.now()-retention) storage.removeItem?.(key);
    } catch (_) { /* Retain damaged or legacy bytes. */ }
  }
}
export function clearOwnerDrafts(storage,owner) {
  for (const key of ownerKeys(storage,owner)) storage.removeItem(key);
}
export const draftPrefix = (page) =>
  `dashboard:wiki:draft:${page.user_id}:${page.id}:`;
export function storeDraft(storage, page, baseRevision, tabId) {
  const key = draftPrefix(page) + tabId;
  const raw = JSON.stringify({
      page: {
        title: page.title,
        content: page.content,
        metadata: page.metadata,
        aliases: page.aliases,
      },
      baseRevision,
      savedAt: new Date().toISOString(),
    });
  if (raw.length*2 > recordLimit) throw new Error('Wiki draft exceeds the recovery limit.');
  prune(storage,page.user_id);
  const others=ownerKeys(storage,page.user_id).filter(existing=>existing!==key);
  if (others.length>=20 || others.reduce((bytes,existing)=>bytes+(storage.getItem(existing)?.length||0)*2,0)+raw.length*2>4*1024*1024) throw new Error('Wiki draft storage is full. Existing copies are retained.');
  storage.setItem(key,raw);
  return key;
}
export function recoverableDrafts(storage, page) {
  prune(storage,page.user_id);
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
