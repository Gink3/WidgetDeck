import React, { useState } from "react";

function textOf(value) {
  return React.Children.toArray(value).map(child =>
    typeof child === "string" || typeof child === "number"
      ? String(child) : textOf(child.props?.children),
  ).join("");
}
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
function compare(a, b) {
  const numeric = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
  if (numeric.test(a) && numeric.test(b)) return Number(a) - Number(b);
  return collator.compare(a, b);
}

function hasMergedCells(node) {
  return Number(node?.properties?.colSpan || 1) > 1 || Number(node?.properties?.rowSpan || 1) > 1
    || (node?.children || []).some(hasMergedCells);
}

export function SortableTable({ children, node, ...props }) {
  const [sort, setSort] = useState(null);
  const sections = React.Children.toArray(children);
  const head = sections.find(section => section.type === "thead");
  const headers = head && React.Children.toArray(head.props.children).filter(React.isValidElement);
  // Preserve complex HTML tables with merged cells or multiple header rows.
  const simple = headers?.length === 1 && !hasMergedCells(node);
  if (!simple) return <table {...props}>{children}</table>;
  return <table {...props}>{sections.map(section => {
    if (section.type === "thead") {
      const row = headers[0];
      return React.cloneElement(section, {}, React.cloneElement(row, {},
        React.Children.toArray(row.props.children).filter(React.isValidElement).map((cell, column) => {
          const direction = sort?.column === column ? sort.direction : null;
          const label = textOf(cell.props.children).trim() || `Column ${column + 1}`;
          return React.cloneElement(cell, { "aria-sort": direction || "none" }, <>
            {cell.props.children}{" "}<button type="button" className="wiki-table-sort"
              aria-label={`Sort ${label} ${direction === "ascending" ? "descending" : "ascending"}`}
              onClick={() => setSort({ column, direction: direction === "ascending" ? "descending" : "ascending" })}>
              <span aria-hidden="true">{direction === "ascending" ? "↑" : direction === "descending" ? "↓" : "↕"}</span>
            </button>
          </>);
        }),
      ));
    }
    if (section.type !== "tbody" || !sort) return section;
    const rows = React.Children.toArray(section.props.children).filter(React.isValidElement);
    const ordered = rows.map((row, index) => ({ row, index, value: textOf(React.Children.toArray(row.props.children).filter(React.isValidElement)[sort.column]?.props.children).trim() }))
      .sort((a, b) => {
        // Empty values stay last and equal values retain their original order.
        if (!a.value || !b.value) return Number(!a.value) - Number(!b.value) || a.index - b.index;
        return compare(a.value, b.value) * (sort.direction === "ascending" ? 1 : -1) || a.index - b.index;
      });
    return React.cloneElement(section, {}, ordered.map(({ row }) => row));
  })}</table>;
}
