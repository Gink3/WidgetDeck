import test from 'node:test';
import assert from 'node:assert/strict';
import { formatTableAt } from '../frontend/src/wiki-tables.mjs';

test('pads columns, preserves alignment, and leaves surrounding prose unchanged', () => {
  const table = '| Name | Amount | Center |\n| :--- | ---: | :---: |\n| Longer name | 3 | x |';
  const text = 'Before\n\n' + table + '\n\nAfter';
  const result = formatTableAt(text, text.indexOf('Longer'));
  assert.equal(result.content, 'Before\n\n| Name        | Amount | Center |\n| :---------- | -----: | :----: |\n| Longer name | 3      | x      |\n\nAfter');
  assert.equal(result.start, 8);
  assert.equal(result.end, result.content.indexOf('\n\nAfter'));
  assert.equal(formatTableAt(result.content, result.start).content, result.content);
});

test('supports missing outer pipes and short rows without losing cells', () => {
  const text = 'A | B\n--- | ---\none';
  const result = formatTableAt(text, 0);
  assert.equal(result.content, '| A   | B   |\n| --- | --- |\none');
  assert.equal(formatTableAt('A | B\n--- | ---\n| one |', 20).content, '| A   | B   |\n| --- | --- |\n| one |     |');
});

test('preserves escaped pipes, code spans, and wiki link labels', () => {
  const text = '| A | B |\n| --- | --- |\n| a\\|b | [[page|Label]] |\n| `x|y` | **bold** |';
  const result = formatTableAt(text, 0);
  for (const cell of ['a\\|b', '[[page|Label]]', '`x|y`', '**bold**']) assert.ok(result.content.includes(cell));
  assert.equal(formatTableAt(result.content, 0).content, result.content);
});

test('targets only the table at the cursor and preserves indentation', () => {
  const first = '| A | B |\n| --- | --- |';
  const second = '  | X | Y |\n  | --- | --- |\n  | Long | z |';
  const text = first + '\n\n' + second;
  const result = formatTableAt(text, text.indexOf('Long'));
  assert.ok(result.content.startsWith(first + '\n\n  | X    | Y   |'));
});

test('does not format prose, fenced code, or indented code', () => {
  for (const text of ['ordinary | prose', '| A | B |\n| -- | --- |', '```md\n| A | B |\n| --- | --- |\n```', '~~~\n| A | B |\n| --- | --- |\n~~~', '    | A | B |\n    | --- | --- |']) {
    assert.equal(formatTableAt(text, text.indexOf('|')), null);
  }
  const text = 'Prose\n\n| A | B |\n| --- | --- |';
  assert.equal(formatTableAt(text, 0), null);
});

test('maps a cursor inside a data cell across table padding', () => {
  const content = 'Before\n| A | B |\n| --- | --- |\n| Longer cell | xyz |\nAfter';
  const caret = content.indexOf('xyz') + 2;
  const result = formatTableAt(content, caret);
  assert.equal(result.caret, result.content.indexOf('xyz') + 2);
  assert.equal(formatTableAt(result.content, result.caret).caret, result.caret);
});

import { editTableAt } from '../frontend/src/wiki-tables.mjs';
test('table tools insert/delete rows and columns and retain rich cells and prose', () => {
  const text='Before\n\n| A | B |\n| :--- | ---: |\n| a\\|b | [[page|Label]] |\n| second | `x|y` |\n\nAfter';
  for (const action of ['row-before','row-after','column-before','column-after']) {
    const result=editTableAt(text,text.indexOf('[[page'),action);
    for (const value of ['Before\n\n','\n\nAfter','a\\|b','[[page|Label]]','`x|y`']) assert.ok(result.content.includes(value));
    assert.ok(result.caret>=result.start && result.caret<=result.end);
  }
  const removed=editTableAt(text,text.indexOf('second'),'delete-row');
  assert.ok(!removed.content.includes('second'));assert.ok(removed.content.includes('[[page|Label]]'));
  const column=editTableAt(text,text.indexOf('[[page'),'delete-column');
  assert.ok(column.content.includes('a\\|b'));assert.ok(!column.content.includes('[[page|Label]]'));
  assert.throws(()=>editTableAt(text,text.indexOf('| A'),'delete-row'),/header/);
  assert.throws(()=>editTableAt('| A |\n| --- |\n| one |',18,'delete-column'),/at least one/);
  assert.throws(()=>editTableAt('```\n| A |\n| --- |\n```',7,'row-after'),/Markdown table/);
});
