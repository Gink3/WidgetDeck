// Split only structural pipes, preserving escaped pipes and wiki link labels.
function cells(line) {
  const text = line.trim();
  const parts = [];
  let cell = "", wiki = false, ticks = 0;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === "\\" && i + 1 < text.length) { cell += char + text[++i]; continue; }
    if (char === "`") {
      const run = text.slice(i).match(/^`+/)[0];
      if (!ticks) ticks = run.length;
      else if (ticks === run.length) ticks = 0;
      cell += run; i += run.length - 1; continue;
    }
    if (!ticks && text.slice(i, i + 2) === "[[") wiki = true;
    if (!ticks && text.slice(i, i + 2) === "]]") wiki = false;
    if (char === "|" && !wiki && !ticks) { parts.push(cell.trim()); cell = ""; }
    else cell += char;
  }
  parts.push(cell.trim());
  if (text.startsWith("|") && parts[0] === "") parts.shift();
  if (text.endsWith("|") && parts.at(-1) === "") parts.pop();
  return parts;
}

export function formatTableAt(content, caret) {
  const lines = content.split("\n");
  const starts = [];
  const eligible = [];
  let offset = 0, fence = null;
  for (const line of lines) {
    starts.push(offset); offset += line.length + 1;
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    eligible.push(!fence && !marker && !/^(?: {4}|\t)/.test(line));
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
    }
  }
  const current = starts.findIndex((start, i) => caret >= start && caret <= start + lines[i].length);
  for (let header = 0; header < lines.length - 1; header++) {
    if (!eligible[header] || !eligible[header + 1] || !lines[header].includes("|")) continue;
    const headings = cells(lines[header]), separator = cells(lines[header + 1]);
    if (!headings.length || separator.length !== headings.length || !separator.every(cell => /^:?-{3,}:?$/.test(cell))) continue;
    const indent = lines[header].match(/^ */)[0];
    const rows = [headings, separator];
    let last = header + 1;
    while (last + 1 < lines.length && eligible[last + 1] && lines[last + 1].includes("|") && lines[last + 1].trim()) {
      const row = cells(lines[last + 1]);
      // Never discard excess cells or merge an adjacent malformed table.
      if (row.length > headings.length || row.every(cell => /^:?-{3,}:?$/.test(cell))) break;
      rows.push([...row, ...Array(headings.length - row.length).fill("")]); last++;
    }
    if (current < header || current > last) continue;
    const widths = headings.map((_, column) => Math.max(3, ...rows.map(row => row[column].length)));
    const formattedLines = rows.map((row, index) => indent + "| " + row.map((cell, column) => {
      if (index !== 1) return cell.padEnd(widths[column]);
      const left = cell.startsWith(":") ? ":" : "";
      const right = cell.endsWith(":") ? ":" : "";
      return left + "-".repeat(widths[column] - left.length - right.length) + right;
    }).join(" | ") + " |");
    const formatted = formattedLines.join("\n");
    const start = starts[header], end = starts[last] + lines[last].length;
    // Track the cursor's row and text position while padding changes around it.
    const rowIndex = current - header, prefix = lines[current].slice(0, caret - starts[current]);
    const textCount = prefix.replace(/\s/g, "").length;
    let at = 0, count = 0;
    while (at < formattedLines[rowIndex].length && count < textCount) {
      if (!/\s/.test(formattedLines[rowIndex][at])) count++;
      at++;
    }
    at += Math.min(prefix.match(/\s*$/)[0].length, formattedLines[rowIndex].slice(at).match(/^\s*/)[0].length);
    const mappedCaret = start + formattedLines.slice(0, rowIndex).reduce((length, line) => length + line.length + 1, 0) + at;
    return { content: content.slice(0, start) + formatted + content.slice(end), start, end: start + formatted.length, caret: mappedCaret, sourceEnd: end, rows, rowIndex, indent, columnIndex: Math.max(0, Math.min(headings.length - 1, cells(prefix + "caret").length - 1)) };
  }
  return null;
}


export function editTableAt(content, caret, action) {
  const table = formatTableAt(content, caret);
  if (!table) throw new Error("Place the cursor in a Markdown table first.");
  const rows = table.rows.map(row => [...row]);
  let row = table.rowIndex, column = table.columnIndex;
  if (action === "row-before" || action === "row-after") {
    row = Math.max(2, row + (action === "row-after" ? 1 : 0));
    rows.splice(row, 0, Array(rows[0].length).fill(""));
  } else if (action === "delete-row") {
    if (row < 2) throw new Error("The header and separator rows are required. Select a data row to delete.");
    rows.splice(row, 1); row = Math.min(row, rows.length - 1);
  } else if (action === "column-before" || action === "column-after") {
    column += action === "column-after" ? 1 : 0;
    rows.forEach((cells, index) => cells.splice(column, 0, index === 0 ? "New column" : index === 1 ? "---" : ""));
  } else if (action === "delete-column") {
    if (rows[0].length === 1) throw new Error("Keep at least one table column.");
    rows.forEach(cells => cells.splice(column, 1)); column = Math.min(column, rows[0].length - 1);
  } else throw new Error("Unknown table action.");
  const lines = rows.map(cells => table.indent + "| " + cells.join(" | ") + " |");
  const changed = content.slice(0, table.start) + lines.join("\n") + content.slice(table.sourceEnd);
  const target = table.start + lines.slice(0,row).reduce((total,line) => total + line.length + 1, 0)
    + table.indent.length + 2 + rows[row].slice(0,column).reduce((total,cell) => total + cell.length + 3, 0);
  return formatTableAt(changed, target);
}
