import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeRange, createRangeState, rangeLabel } from '../src/range.js';
const frame = (sequence=0) => ({type:'range_update',schema_version:1,delivery:'synthetic',
 observation:{type:'range_observation',schema_version:1,sensor_id:'synthetic-sensor',session_id:'synthetic-session',sensor_model:'SYNTHETIC test fixture',sequence,capture_timestamp:1735689600000,timestamp_basis:'unix_ms',distance_m:1.2,valid:true,timed_out:false,status:'valid',source:'synthetic',calibration_status:'unverified'},
 statistics:{sample_count:3,valid_count:3,missing_count:0,invalid_count:0,outlier_count:0,median_m:1.2,spread_m:0.02,raw_spread_m:0.02,available:true,reference_m:null,absolute_error_m:null}});
test('independent measured-range decoder preserves provenance without geometry',()=>{
 const result=decodeRange(JSON.stringify(frame())); assert.equal(result.range.observation.distance_m,1.2);
 assert.equal(rangeLabel(result.range),'SYNTHETIC'); assert.equal(result.points,undefined);
 const replay={...frame(),delivery:'replay'}; assert.equal(rangeLabel(decodeRange(JSON.stringify(replay)).range),'REPLAY · SYNTHETIC');
});
test('missing returns display as unavailable, never zero',()=>{
 const raw=frame(); Object.assign(raw.observation,{distance_m:null,status:'timeout',valid:false,timed_out:true});
 Object.assign(raw.statistics,{available:false,median_m:null}); assert.equal(decodeRange(JSON.stringify(raw)).range.observation.distance_m,null);
});
test('malformed/nonfinite readings and false provenance rejected',()=>{
 for(const mutate of [o=>o.observation.distance_m=-1,o=>o.observation.distance_m=null,o=>o.delivery='live',o=>o.observation.source='lidar',o=>o.statistics.median_m='1']){
   const o=frame(); mutate(o); assert.throws(()=>decodeRange(JSON.stringify(o)));
 }
 assert.throws(()=>decodeRange('{broken}')); assert.throws(()=>decodeRange(JSON.stringify({type:'range_update',schema_version:9})));
});
test('bounded per-sensor history ignores duplicates and resets on new session',()=>{
 const state=createRangeState({historySize:3}); for(let i=0;i<20;i++) state.accept(frame(i));
 assert.equal(state.values()[0].history.length,3); assert.equal(state.accept(frame(19)),false);
 const reset=frame(); reset.observation.session_id='synthetic-new'; state.accept(reset);
 assert.equal(state.values()[0].history.length,1); state.clear(); assert.equal(state.values().length,0);
});
test('independent sensors do not share mutable history',()=>{
 const state=createRangeState();state.accept(frame()); const b=frame();b.observation.sensor_id='synthetic-other';state.accept(b);
 assert.equal(state.values().length,2);state.values()[0].history.push({});assert.equal(state.values()[1].history.length,1);
});
