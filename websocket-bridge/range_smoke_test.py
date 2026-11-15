"""SYNTHETIC-only CLI -> adapter -> relay -> JS readout -> recording -> replay."""
import asyncio
import json
from pathlib import Path
import random
import re
import sys
import tempfile
from websockets.asyncio.client import connect
from fake_phone import frame as synthetic_lidar

ROOT=Path(__file__).resolve().parent
ORIGIN="http://127.0.0.1:4180"


async def start(*args):
    process=await asyncio.create_subprocess_exec(sys.executable,"-B","-m","sonar_bridge",
         "--host","127.0.0.1","--port","0","--origin",ORIGIN,"--allow-no-origin",*args,cwd=ROOT,
         stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        line=await asyncio.wait_for(process.stdout.readline(),8)
        match=re.search(rb":([0-9]+)/range/view",line)
        if not match: raise RuntimeError("range server startup failed")
        return process,f"ws://127.0.0.1:{int(match[1])}"
    except BaseException:
        await stop(process); raise


async def stop(process):
    if process.returncode is None: process.terminate()
    return await asyncio.wait_for(process.communicate(),5)


async def receive_kind(client,kind):
    async with asyncio.timeout(3):
        while True:
            item=json.loads(await client.recv())
            if item["type"]==kind: return item


CLIENT="""
import assert from 'node:assert/strict';
import { openFeed } from './src/feed.js';
import { decodeRange, createRangeState, rangeLabel } from './src/range.js';
const [url, mode] = process.argv.slice(1), updates = [], state = createRangeState();
let stop;
await new Promise((resolve,reject)=>{
 const timer=setTimeout(()=>{stop?.();reject(new Error('range client timeout'))},10000);
 stop=openFeed(url,{decode:decodeRange,onStatus(status){
   if(status==='connected') console.log('READY');
   if(status==='error'){clearTimeout(timer);reject(new Error('range socket error'))}
   if(status==='complete'){clearTimeout(timer);resolve()}
 },onInvalid(error){clearTimeout(timer);reject(error)},onFrame(frame){
   if(!frame.range)return;
   assert.equal(frame.range.observation.source,'synthetic');
   assert.equal(frame.range.delivery,mode==='replay'?'replay':'synthetic');
   state.accept(frame.range);updates.push(frame.range);
   if(mode==='capture'&&updates.length===5){clearTimeout(timer);stop();resolve()}
 }});
});
assert.equal(updates.length,5);
assert.deepEqual(updates.map(u=>u.observation.sequence),[0,1,2,3,4]);
assert.equal(updates[1].observation.distance_m,null);
assert.equal(updates[4].statistics.available,true);
assert.equal(state.values()[0].history.length,5);
assert.match(rangeLabel(updates[4]),/SYNTHETIC/);
console.log(JSON.stringify(updates));
"""


async def client(url,mode):
    process=await asyncio.create_subprocess_exec("node","--input-type=module","-e",CLIENT,url+"/range/view",mode,
            cwd=ROOT.parent,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        assert (await asyncio.wait_for(process.stdout.readline(),5)).strip()==b"READY"
    except BaseException as exc:
        out,err=await stop(process)
        raise RuntimeError("Node range client startup failed: "+(out+err).decode()) from exc
    return process


async def finish_client(process):
    stdout,stderr=await asyncio.wait_for(process.communicate(),15)
    if process.returncode: raise AssertionError((stdout+stderr).decode())
    return json.loads(stdout)


async def main():
    (ROOT/".tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="range-smoke-",dir=ROOT/".tmp") as folder:
        path=Path(folder)/"synthetic-capture.jsonl"
        server,url=await start("--range","--lidar","--range-record",str(path))
        consumer=None; publisher=None
        try:
            async with connect(url+"/ws",origin=ORIGIN,proxy=None) as sonar:
                assert (await receive_kind(sonar,"sonar_frame"))["source"]=="simulated"
            async with connect(url+"/lidar/view",origin=ORIGIN,proxy=None) as lv,connect(url+"/lidar/publish",proxy=None) as lp:
                value=synthetic_lidar(0,"synthetic-range-smoke",random.Random(0))
                await lp.send(json.dumps(value))
                assert (await receive_kind(lv,"lidar_frame"))["points"]==value["points"]
            consumer=await client(url,"capture")
            publisher=await asyncio.create_subprocess_exec(sys.executable,"-B","-m","sonar_bridge.range_adapter",
                "--fixture","fixtures/range-synthetic.txt","--format","meters-line","--url",url+"/range/publish",
                "--fps","10",cwd=ROOT,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            original=await finish_client(consumer)
            out,err=await asyncio.wait_for(publisher.communicate(),5)
            assert publisher.returncode==0,(out+err).decode()
            assert b"SYNTHETIC FIXTURE ONLY" in out
        finally:
            for process in (publisher,consumer):
                if process and process.returncode is None: await stop(process)
            await stop(server)
        server,url=await start("--range-replay",str(path),"--range-fps","30")
        consumer=None
        try:
            consumer=await client(url,"replay")
            replayed=await finish_client(consumer)
            assert replayed==[{**o,"delivery":"replay"} for o in original]
        finally:
            if consumer and consumer.returncode is None: await stop(consumer)
            await stop(server)
    print("RANGE SMOKE PASS: 5 SYNTHETIC observations -> real adapter/relay/JS decoder + history -> JSONL -> replay; source, timestamps, raw units and statistics preserved. Sonar /ws and existing LiDAR passed. All test processes stopped.")
    print("REAL HARDWARE TESTS: BLOCKED (models, electrical compatibility and firmware format NOT YET VERIFIED)")


if __name__=="__main__": asyncio.run(main())
