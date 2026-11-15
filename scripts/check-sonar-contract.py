"""Synthetic-only protocol contract check against an existing PR #6 checkout. No serial ports opened."""
import argparse
import importlib
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--range-root',type=Path,required=True,help='PR #6 websocket-bridge directory')
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
if not (args.range_root/'sonar_bridge/range_adapter.py').is_file():
    parser.error('Expected an existing range adapter checkout; no files will be copied')
sys.path.insert(0,str(args.range_root.resolve()))
from sonar_bridge.range_adapter import Profile, ObservationBuilder
from sonar_bridge.range_protocol import encode
from lidar_mapper.sonar import parse_line, MIN_RANGE, MAX_RANGE
builder=ObservationBuilder(Profile('synthetic-contract',model='HC-SR04 SYNTHETIC contract fixture',
    modality='ultrasonic',min_m=MIN_RANGE,max_m=MAX_RANGE),session_id='synthetic-contract-session',now_ms=lambda:1735689600000)
rows=[]
for line,status in [('1.234','valid'),('0.030','valid'),('4.000','valid'),('timeout','timeout'),('nan','invalid'),('0','invalid'),('# hcsr04 trig pin 6 echo pin 5','invalid'),('1e0','invalid')]:
    observation=builder.line(line,'meters-line')
    assert observation['status']==status
    assert json.loads(encode(observation))==observation
    parsed=parse_line(line)
    if status=='valid': assert parsed==observation['distance_m']
    if status=='timeout': assert parsed is None and observation['distance_m'] is None
    assert observation['source']=='synthetic' and observation['sensor_pose'] is None
    rows.append({'input':line,'mapper_parse_m':parsed,'range_status':status,'range_m':observation['distance_m']})
args.out.parent.mkdir(parents=True,exist_ok=True)
with args.out.open('x',encoding='utf-8') as file:
    json.dump({'source':'synthetic','physical_serial_opened':False,'checks':rows,'passed':len(rows),
        'range_adapter':str(importlib.import_module('sonar_bridge.range_adapter').__file__)},file,indent=2,allow_nan=False)
print(f'PASS: {len(rows)} synthetic contract cases. No physical acquisition. Exponent input is accepted only by mapper; firmware emits decimal meters.')
