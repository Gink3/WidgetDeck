// Compare editable content, not server bookkeeping or object insertion order.
export function mapFingerprint(map) {
  if (!map) return '';
  const pick = (value, keys) => Object.fromEntries(keys.map(key=>[key,value[key]]));
  const content = {...pick(map,['name','description','viewport','layout_mode','settings']),
    nodes:map.nodes.map(node=>pick(node,['id','title','description','x','y','width','height','type','collapsed','metadata','style_override'])),
    edges:map.edges.map(edge=>pick(edge,['id','source_id','target_id','kind','label','directed']))};
  return JSON.stringify(content,(_,value)=>value && typeof value==='object' && !Array.isArray(value)
    ? Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])) : value);
}
