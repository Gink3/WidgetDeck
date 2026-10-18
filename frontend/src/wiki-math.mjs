// Ignore code and escaped dollars when locating the equation under the caret.
export function equationAt(content, caret) {
  const tokens = /(^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}\2[^\n]*(?:\n|$)|(?![\s\S])))|(`+)[^`]*?\3|\\[\s\S]|\${1,2}/gm;
  let open = null;
  for (const match of content.matchAll(tokens)) {
    const token = match[0];
    if (token !== "$" && token !== "$$") continue;
    if (!open) {
      open = { start: match.index, delimiter: token };
    } else if (token === open.delimiter) {
      const start = open.start + token.length;
      if (caret >= start && caret <= match.index) {
        return { source: content.slice(start, match.index), display: token === "$$" };
      }
      open = null;
    }
  }
  if (open && caret >= open.start + open.delimiter.length) {
    const source = content.slice(open.start + open.delimiter.length);
    if (open.delimiter === "$$" || !source.includes("\n")) {
      return { source, display: open.delimiter === "$$" };
    }
  }
  return null;
}

// Common KaTeX commands, with readable symbols to help discover the right one.
const symbols = [
  ['alpha', 'α', 'alpha'], ['beta', 'β', 'beta'], ['gamma', 'γ', 'gamma'],
  ['delta', 'δ', 'delta'], ['theta', 'θ', 'theta'], ['pi', 'π', 'pi'],
  ['epsilon', 'ϵ', 'epsilon'], ['varepsilon', 'ε', 'epsilon variant'],
  ['zeta', 'ζ', 'zeta'], ['eta', 'η', 'eta'], ['vartheta', 'ϑ', 'theta variant'],
  ['iota', 'ι', 'iota'], ['kappa', 'κ', 'kappa'], ['lambda', 'λ', 'lambda'],
  ['mu', 'μ', 'mu'], ['nu', 'ν', 'nu'], ['xi', 'ξ', 'xi'],
  ['rho', 'ρ', 'rho'], ['sigma', 'σ', 'sigma'], ['tau', 'τ', 'tau'],
  ['upsilon', 'υ', 'upsilon'], ['phi', 'ϕ', 'phi'], ['varphi', 'φ', 'phi variant'],
  ['chi', 'χ', 'chi'], ['psi', 'ψ', 'psi'], ['omega', 'ω', 'omega'],
  ['Gamma', 'Γ', 'capital gamma'], ['Delta', 'Δ', 'capital delta'],
  ['Theta', 'Θ', 'capital theta'], ['Lambda', 'Λ', 'capital lambda'],
  ['Xi', 'Ξ', 'capital xi'], ['Pi', 'Π', 'capital pi'], ['Sigma', 'Σ', 'capital sigma'],
  ['Phi', 'Φ', 'capital phi'], ['Psi', 'Ψ', 'capital psi'], ['Omega', 'Ω', 'capital omega'],
  ['times', '×', 'multiply'], ['cdot', '⋅', 'dot product'], ['div', '÷', 'divide'],
  ['pm', '±', 'plus or minus'], ['mp', '∓', 'minus or plus'],
  ['leq', '≤', 'less than or equal'], ['geq', '≥', 'greater than or equal'],
  ['neq', '≠', 'not equal'], ['approx', '≈', 'approximately equal'],
  ['equiv', '≡', 'equivalent'], ['propto', '∝', 'proportional'],
  ['infty', '∞', 'infinity'], ['partial', '∂', 'partial derivative'], ['nabla', '∇', 'gradient'],
  ['sum', '∑', 'sum'], ['prod', '∏', 'product'], ['int', '∫', 'integral'],
  ['iint', '∬', 'double integral'], ['oint', '∮', 'contour integral'],
  ['in', '∈', 'element of'], ['notin', '∉', 'not an element'], ['subset', '⊂', 'subset'],
  ['subseteq', '⊆', 'subset or equal'], ['cup', '∪', 'union'], ['cap', '∩', 'intersection'],
  ['emptyset', '∅', 'empty set'], ['forall', '∀', 'for all'], ['exists', '∃', 'exists'],
  ['neg', '¬', 'logical not'], ['land', '∧', 'logical and'], ['lor', '∨', 'logical or'],
  ['to', '→', 'arrow'], ['rightarrow', '→', 'right arrow'], ['leftarrow', '←', 'left arrow'],
  ['Rightarrow', '⇒', 'implies'], ['Leftrightarrow', '⇔', 'if and only if'],
  ['sin', 'sin', 'sine'], ['cos', 'cos', 'cosine'], ['tan', 'tan', 'tangent'],
  ['log', 'log', 'logarithm'], ['ln', 'ln', 'natural logarithm'], ['lim', 'lim', 'limit'],
  ['ldots', '…', 'ellipsis'], ['cdots', '⋯', 'centered dots'],
];
const templates = [
  ['sqrt', '\\sqrt{}', '√ square root'], ['frac', '\\frac{}{}', 'fraction'],
  ['text', '\\text{}', 'text in equation'], ['mathbf', '\\mathbf{}', 'bold'],
  ['mathbb', '\\mathbb{}', 'blackboard bold'], ['mathrm', '\\mathrm{}', 'upright text'],
  ['vec', '\\vec{}', 'vector'], ['hat', '\\hat{}', 'hat accent'],
  ['bar', '\\bar{}', 'bar accent'], ['overline', '\\overline{}', 'overline'],
  ['underbrace', '\\underbrace{}', 'underbrace'],
];
export const mathCommands = [
  ...symbols.map(([name, symbol, description]) => ({ name, label: `\\${name} — ${symbol} ${description}`, value: `\\${name} ` })),
  ...templates.map(([name, value, description]) => ({ name, label: `\\${name} — ${description}`, value, caret: value.indexOf('{') + 1 })),
];

export function mathCompletionAt(content, caret) {
  if (!equationAt(content, caret)) return null;
  const prefix = content.slice(0, caret);
  const match = prefix.match(/(\\+)([a-zA-Z]*)$/);
  if (!match || match[1].length % 2 === 0) return null;
  const query = match[2];
  const matches = mathCommands.filter(item => item.name.startsWith(query));
  const suffix = content.slice(caret).match(/^[a-zA-Z]*/)[0];
  return {
    kind: 'math', start: caret - query.length - 1, end: caret + suffix.length,
    items: matches.slice(0, 8),
  };
}
