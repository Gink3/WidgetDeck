export const figureTemplate = ":::figure right\n![Image description](/path/to/image.jpg)\n\nCaption for this image.\n:::\n";

// Recognize complete figure blocks outside Markdown fences. Leave incomplete
// or malformed blocks untouched so editing never hides the source text.
export function figureBlocks(content) {
  const lines = content.split(/(?<=\n)/);
  const parts = [];
  let plain = "", fence = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\r?\n$/, "");
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      plain += lines[i];
      if (marker && marker[1][0] === fence.char && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
      continue;
    }
    if (marker) { fence = { char: marker[1][0], length: marker[1].length }; plain += lines[i]; continue; }
    if (!/^ {0,3}:::figure right\s*$/.test(line)) { plain += lines[i]; continue; }
    let end = i + 1;
    while (end < lines.length && !/^ {0,3}:::\s*$/.test(lines[end])) end++;
    if (end === lines.length) { plain += lines[i]; continue; }
    const body = lines.slice(i + 1, end).join("").trim();
    const firstLine = body.split(/\r?\n/, 1)[0];
    if (!/^!\[(?:\\.|[^\]\\])*\]\(.+\)$/.test(firstLine)) { plain += lines[i]; continue; }
    if (plain) parts.push({ type: "markdown", content: plain });
    parts.push({ type: "figure", image: firstLine, caption: body.slice(firstLine.length).trim() });
    plain = "";
    i = end;
  }
  if (plain) parts.push({ type: "markdown", content: plain });
  return parts;
}
