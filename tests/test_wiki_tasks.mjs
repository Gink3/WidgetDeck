import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeTaskLists } from '../frontend/src/wiki-utils.mjs';

test('bare checkbox lines become task items and preserve nested bullets', () => {
  const input = '## TODO\n[ ] Set minimum distance of stairs from towns\n[ ] Set the number of stairs per levels\n[ ] Soft Skills\n  * Trading/Bartering\n  * Persuasion\n[x] Item quality system';
  const result = normalizeTaskLists(input);
  assert.equal(result, input.replace(/^\[/gm, '- ['));
  assert.equal(normalizeTaskLists(result), result);
});
test('code, ordinary brackets, and existing task lists stay unchanged', () => {
  const input = '```md\n[ ] Example\n```\n~~~\n[x] Example\n~~~\n    [ ] Code\n- [ ] Existing\n[link](url)\n\\[ ] Literal';
  assert.equal(normalizeTaskLists(input), input);
});
