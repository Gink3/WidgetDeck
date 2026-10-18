import test from 'node:test';
import assert from 'node:assert/strict';
import { equationAt } from '../frontend/src/wiki-math.mjs';

test('locates inline and multiline display equations', () => {
  assert.deepEqual(equationAt('Text $x^2$ end', 8), { source: 'x^2', display: false });
  assert.deepEqual(equationAt('$$\n\\frac{1}{2}\n$$', 8), { source: '\n\\frac{1}{2}\n', display: true });
  assert.equal(equationAt('$x$ plain', 7), null);
});
test('previews unfinished equations while typing', () => {
  assert.deepEqual(equationAt('$\\frac{', 7), { source: '\\frac{', display: false });
  assert.deepEqual(equationAt('$$\nx +', 6), { source: '\nx +', display: true });
});
test('ignores escaped dollars and code', () => {
  for (const content of ['Price \\$5', '`$x$`', '```tex\n$x$\n```', '~~~\n$x$\n~~~']) {
    assert.equal(equationAt(content, content.indexOf('x') + 1), null);
  }
});

const { mathCompletionAt, mathCommands } = await import('../frontend/src/wiki-math.mjs');
const { completionAt } = await import('../frontend/src/wiki-utils.mjs');

test('backslash commands suggest readable symbols in inline and display equations', () => {
  for (const text of ['$\\alp', '$$\n\\alp']) {
    const result = completionAt(text, text.length, [], [], []);
    assert.equal(result.kind, 'math');
    assert.equal(result.items[0].value, '\\alpha ');
    assert.match(result.items[0].label, /α/);
  }
  assert.equal(mathCompletionAt('$\\', 2).items.length, 8);
  assert.equal(mathCompletionAt('$\\Gamma', 7).items[0].name, 'Gamma');
});

test('templates place the caret inside the first argument', () => {
  for (const name of ['frac', 'sqrt', 'vec', 'mathbb']) {
    const text = '$\\' + name;
    const item = mathCompletionAt(text, text.length).items[0];
    assert.equal(item.name, name);
    assert.equal(item.value[item.caret - 1], '{');
    assert.equal(item.value[item.caret], '}');
  }
});

test('completion replaces the whole command when editing its middle', () => {
  const text = '$\\alpha + x$';
  const result = mathCompletionAt(text, 4);
  assert.equal(result.start, 1);
  assert.equal(result.end, 7);
  assert.equal(text.slice(0, result.start) + result.items[0].value + text.slice(result.end), '$\\alpha  + x$');
});

test('does not suggest in prose, code, escaped backslashes, or after math', () => {
  for (const text of ['plain \\alp', '`$\\alp`', '```tex\n$\\alp\n```', '~~~\n$\\alp\n~~~', '$\\\\alp', '$x$ \\alp']) {
    const caret = text.includes('alp') ? text.indexOf('alp') + 3 : text.length;
    assert.equal(mathCompletionAt(text, caret), null, text);
  }
  assert.deepEqual(mathCompletionAt('$\\unknowncommand', 16).items, []);
  assert.equal(new Set(mathCommands.map(item => item.name)).size, mathCommands.length);
});
