import test from 'node:test';
import assert from 'node:assert/strict';
import { figureBlocks, figureTemplate } from '../frontend/src/wiki-figures.mjs';
import { builtins, expandMacro } from '../frontend/src/wiki-utils.mjs';

test('figures retain image Markdown, captions, and surrounding text', () => {
  const result = figureBlocks('Before\n\n' + figureTemplate + '\nAfter');
  assert.equal(result.length, 3);
  assert.equal(result[1].type, 'figure');
  assert.equal(result[1].image, '![Image description](/path/to/image.jpg)');
  assert.equal(result[1].caption, 'Caption for this image.');
  assert.equal(result[2].content, '\nAfter');
});
test('fenced examples, malformed and unfinished blocks stay literal', () => {
  for (const text of ['```markdown\n' + figureTemplate + '```', '~~~~\n' + figureTemplate + '~~~~', ':::figure right\n![alt](image.png)', ':::figure right\nNot an image\n:::\n', '    :::figure right\n![alt](image.png)\n:::']) {
    assert.ok(figureBlocks(text).every(p => p.type === 'markdown'));
    assert.equal(figureBlocks(text).map(p => p.content).join(''), text);
  }
});
test('multiple figures, CRLF and empty captions work', () => {
  const text = ':::figure right\r\n![alt](https://example.com/a_(b).png)\r\n:::\r\n';
  const result = figureBlocks(text + figureTemplate);
  assert.equal(result.filter(p => p.type === 'figure').length, 2);
  assert.equal(result[0].caption, '');
});
test('figure macro expands to the new block', () => {
  assert.equal(expandMacro(':::figure', 9, builtins).content, figureTemplate);
});
