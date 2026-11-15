"""Range relay plus narrow routing to existing sonar and LiDAR services.

No competing LiDAR implementation: delegate its routes to the existing service.
"""
from __future__ import annotations
import asyncio
import json
import logging
from http import HTTPStatus
from typing import Any
from websockets.asyncio.server import serve,ServerConnection
from websockets.exceptions import ConnectionClosed
from .lidar import _Viewer,_Access,MAX_FRAME_BYTES
from .server import Bridge,DEFAULT_ORIGINS
from .range_protocol import MAX_BYTES,decode,encode
from .range_processing import Policy,RangeProcessor
from .range_recording import RangeRecorder,read_range_recording

LOGGER=logging.getLogger(__name__)


def update(o:dict,summary:dict,*,replay:bool=False) -> str:
    delivery="replay" if replay else {"hardware":"live","manual":"manual","synthetic":"synthetic"}[o["source"]]
    return json.dumps({"type":"range_update","schema_version":1,"delivery":delivery,
                       "observation":o,"statistics":summary},allow_nan=False,separators=(",",":"))


class RangeHub:
    def __init__(self,*,origins:tuple[str,...]=DEFAULT_ORIGINS,allow_no_origin:bool=False,
                 policy:Policy=Policy(),record:RangeRecorder|None=None,backlog:int=16,max_viewers:int=8):
        if not 1<=backlog<=128 or not 1<=max_viewers<=32: raise ValueError("invalid bounded client limits")
        self.access=_Access(origins,allow_no_origin)
        self.processor=RangeProcessor(policy); self.record=record
        self.backlog=backlog; self.max_viewers=max_viewers
        self.viewers:set[_Viewer]=set()
        self.publishers:dict[ServerConnection,str|None]={}
        self.latest:dict[str,str]={}
        self.accepted=0; self.rejected=0; self.dropped=0
        self.lock=asyncio.Lock()

    def check_request(self,connection,request):
        values=request.headers.get_all("Origin")
        if len(values)>1: return connection.respond(HTTPStatus.FORBIDDEN,"Invalid Origin\n")
        origin=values[0] if values else None
        if request.path=="/range/publish":
            return None if origin is None else connection.respond(HTTPStatus.FORBIDDEN,"Native adapters only\n")
        if request.path!="/range/view": return connection.respond(HTTPStatus.NOT_FOUND,"Unknown range route\n")
        return None if self.access.viewer_allowed(origin) else connection.respond(HTTPStatus.FORBIDDEN,"Origin not allowed\n")

    def status(self):
        return json.dumps({"type":"range_status","schema_version":1,"mode":"live",
                           "publisher_connected":bool(self.publishers),"recording":self.record is not None})

    def broadcast(self,message):
        for viewer in self.viewers:
            if len(viewer.outbox)==viewer.outbox.maxlen: self.dropped+=1
            viewer.push(message)

    async def accept(self,raw:str,connection:ServerConnection|None=None) -> None:
        o=decode(raw)
        async with self.lock:
            if connection is not None:
                bound=self.publishers[connection]
                if bound is not None and bound!=o["sensor_id"]: raise ValueError("publisher cannot change sensor identity")
                if any(c is not connection and sensor==o["sensor_id"] for c,sensor in self.publishers.items()):
                    raise ValueError("sensor already has an active publisher")
            self.processor.check(o)
            if self.record: await asyncio.to_thread(self.record.append,o)
            summary=self.processor.add(o)
            if connection is not None: self.publishers[connection]=o["sensor_id"]
            message=update(o,summary)
            self.latest[o["sensor_id"]]=message
            self.accepted+=1
            self.broadcast(message)
            LOGGER.info(json.dumps({"event":"range_accepted","sensor_id":o["sensor_id"],"session_id":o["session_id"],
                                    "sequence":o["sequence"],"source":o["source"],"status":o["status"],
                                    "accepted":self.accepted,"dropped":self.dropped}))

    async def publish(self,connection):
        if len(self.publishers)>=4:
            await connection.close(1013,"range publisher limit"); return
        self.publishers[connection]=None
        self.broadcast(self.status())
        try:
            async for raw in connection:
                try: await self.accept(raw,connection)
                except ValueError:
                    self.rejected+=1
                    await connection.close(1008,"invalid range observation/order/identity"); return
                except OSError:
                    await connection.close(1011,"range recording unavailable"); return
        except ConnectionClosed: pass
        finally:
            self.publishers.pop(connection,None)
            self.broadcast(self.status())

    async def handler(self,connection):
        if connection.request.path=="/range/publish": await self.publish(connection)
        else: await self.view(connection)

    async def view(self,connection):
        if len(self.viewers)>=self.max_viewers:
            await connection.close(1013,"range viewer limit"); return
        viewer=_Viewer(self.backlog)
        viewer.push(self.status())
        # Limit initial snapshots to the same bounded queue, never a full history.
        for message in self.latest.values(): viewer.push(message)
        self.viewers.add(viewer)
        closed=asyncio.create_task(connection.wait_closed())
        ready=None
        try:
            while not closed.done():
                while viewer.outbox:
                    await asyncio.wait_for(connection.send(viewer.outbox.popleft()),5)
                viewer.ready.clear()
                ready=asyncio.create_task(viewer.ready.wait())
                done,_=await asyncio.wait({ready,closed},return_when=asyncio.FIRST_COMPLETED)
                if closed in done: return
        except TimeoutError: await connection.close(1013,"slow range viewer")
        except ConnectionClosed: pass
        finally:
            for task in (ready,closed):
                if task is not None: task.cancel()
            await asyncio.gather(*(task for task in (ready,closed) if task is not None),return_exceptions=True)
            self.viewers.discard(viewer)


class RangeReplay:
    def __init__(self,path,*,fps:float=5,origins=DEFAULT_ORIGINS,allow_no_origin=False):
        if not 0<fps<=30: raise ValueError("range replay FPS 0..30")
        self.policy,self.observations=read_range_recording(path)
        self.interval=1/fps; self.access=_Access(origins,allow_no_origin)

    def check_request(self,connection,request):
        if request.path!="/range/view": return connection.respond(HTTPStatus.NOT_FOUND,"Range replay is read only\n")
        values=request.headers.get_all("Origin")
        if len(values)>1 or not self.access.viewer_allowed(values[0] if values else None):
            return connection.respond(HTTPStatus.FORBIDDEN,"Origin not allowed\n")
        return None

    async def handler(self,connection):
        processor=RangeProcessor(self.policy)
        try:
            await connection.send(json.dumps({"type":"range_status","schema_version":1,"mode":"replay","publisher_connected":False,"recording":False}))
            for o in self.observations:
                await asyncio.wait_for(connection.send(update(o,processor.add(o),replay=True)),5)
                try:
                    await asyncio.wait_for(connection.wait_closed(),self.interval); return
                except TimeoutError: pass
            await connection.close(1000,"source complete")
        except (ConnectionClosed,TimeoutError): pass


def start_range_server(sonar:Bridge,ranges:RangeHub|RangeReplay,*,lidar=None,host:str="127.0.0.1",port:int=8765,
                       origins=DEFAULT_ORIGINS,allow_no_origin=False):
    """One listener, original implementations on /ws and /lidar/*, new /range/*."""
    access=_Access(origins,allow_no_origin)
    def request(connection,req):
        if req.path.startswith("/range/"):
            result=ranges.check_request(connection,req); limit=MAX_BYTES
        elif req.path.startswith("/lidar/") and lidar is not None:
            result=lidar.check_request(connection,req); limit=MAX_FRAME_BYTES
        elif req.path=="/ws":
            values=req.headers.get_all("Origin")
            result=None if len(values)<=1 and access.viewer_allowed(values[0] if values else None) else connection.respond(HTTPStatus.FORBIDDEN,"Origin not allowed\n")
            limit=1024
        else: return connection.respond(HTTPStatus.NOT_FOUND,"Unknown WebSocket route\n")
        if hasattr(connection.protocol,"max_message_size"): connection.protocol.max_message_size=limit
        else: connection.protocol.max_size=limit
        return result
    async def handler(connection):
        if connection.request.path.startswith("/range/"): await ranges.handler(connection)
        elif connection.request.path.startswith("/lidar/"): await lidar.handler(connection)
        else: await sonar.handler(connection)
    return serve(handler,host,port,process_request=request,max_size=MAX_FRAME_BYTES,max_queue=4,
                 close_timeout=2,compression=None)
