import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mapFingerprint} from '../frontend/src/mindmap-state.mjs';
test('Mind map baseline ignores server bookkeeping while retaining editable content',()=>{
  const map={name:'Map',description:'',layout_mode:'freeform',viewport:{x:0,y:0,zoom:1},settings:{},nodes:[{id:'a',title:'Node',x:0,y:0,metadata:{b:2,a:1}}],edges:[]};
  const saved={...map,id:'server-map-id',created_at:'one',updated_at:'two',nodes:map.nodes.map(node=>({...node,map_id:'server-map-id',created_at:'new',updated_at:'new',metadata:{a:1,b:2}}))};
  assert.equal(mapFingerprint(map),mapFingerprint(saved));
  assert.notEqual(mapFingerprint(map),mapFingerprint({...saved,nodes:[{...saved.nodes[0],title:'Edited'}]}));
  assert.notEqual(mapFingerprint(map),mapFingerprint({...map,settings:{grid:false}}));
});
