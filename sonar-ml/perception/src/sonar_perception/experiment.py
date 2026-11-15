"""One predeclared synthetic-data candidate; never modifies production inference.

Run from sonar-ml/: python -m sonar_perception.experiment --root data/<new-run>.
Prepare immutable inputs before fitting; train/evaluate can be resumed separately.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from .augmentation import AcquisitionDiversity
from .dataset import generate, load_clusters, split_by_scene
from .diagnostics import object_outcomes, summarize
from .features import FEATURE_NAMES
from .frame import SonarFrame
from .inference import ForestClassifier, detect_frame
from .detections import frame_detections_dict
from .sim import CLASSES

SETTINGS = {"source": "synthetic", "training_scenes": 400, "eval_scenes": 120,
    "training_seed": 20261115, "standard_seed": 424242, "challenge_seed": 424243,
    "split_seed": 0, "test_fraction": .2, "forest_seeds": [0,1,2],
    "forest": {"n_estimators": 300, "class_weight": "balanced", "n_jobs": 1},
    "sensing": {"pings_averaged": 1, "sweep_poses": 1},
    "decision_rule": "Adopt only if standard macro-F1 drop <=0.01, challenge macro-F1 gain >=0.02, and standard person end-to-end recall drop <=0.02. Otherwise retain baseline. Real performance unvalidated."}


def dump(path, value):
    with Path(path).open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, allow_nan=False)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def prepare(root):
    root.mkdir(parents=True, exist_ok=True)
    specs = [("baseline-train",400,20261115,None,False), ("eval-standard",120,424242,None,True),
        ("eval-challenge",120,424243,AcquisitionDiversity.challenge(),True),
        ("candidate-train",400,20261115,AcquisitionDiversity(),False)]
    for name, count, seed, diversity, frames in specs:
        path = root / name
        if (path / "manifest.json").exists():
            saved = json.loads((path/"manifest.json").read_text())
            expected_diversity = json.loads(json.dumps(asdict(diversity))) if diversity else None
            if saved['seed'] != seed or saved['n_scenes'] != count or saved.get('diversity') != expected_diversity:
                raise ValueError(f"Existing dataset configuration disagrees: {path}; choose a new root")
            if not (path/'clusters.npz').is_file(): raise ValueError(f"Incomplete dataset: {path}")
            print(f"Reusing immutable {name}",flush=True)
            continue
        if path.exists(): raise ValueError(f"Incomplete dataset directory exists: {path}; preserve it and choose a new root")
        print(f"Generating {name}: {count} scenes, seed {seed}",flush=True)
        generate(path,count,seed=seed,diversity=diversity,save_frames=frames)
    lock={"settings":SETTINGS,"datasets":{name:{"manifest":json.loads((root/name/'manifest.json').read_text()),
        "sha256":digest(root/name/'clusters.npz'),
        "frames":{f.name:digest(f) for f in sorted((root/name/'scenes').glob('*.npz'))}}
        for name,*_ in specs}}
    if (root/'inputs.json').exists():
        if json.loads((root/'inputs.json').read_text()) != lock: raise ValueError("Locked inputs changed")
    else: dump(root/'inputs.json',lock)


def scores(clf, d):
    start=time.perf_counter(); pred=clf.predict(d['features']); elapsed=time.perf_counter()-start
    return {"n":len(pred),"accuracy":float(accuracy_score(d['labels'],pred)),
        "per_env_accuracy":{str(e):float(accuracy_score(d['labels'][d['env']==e],pred[d['env']==e])) for e in np.unique(d['env'])},
        "report":classification_report(d['labels'],pred,labels=list(CLASSES),target_names=list(CLASSES.values()),output_dict=True,zero_division=0),
        "confusion_matrix":confusion_matrix(d['labels'],pred,labels=list(CLASSES)).tolist(),
        "inference_ms_per_cluster":elapsed*1000/max(1,len(pred))},pred


def evaluate(root):
    locked=json.loads((root/'inputs.json').read_text())
    for name, info in locked['datasets'].items():
        if digest(root/name/'clusters.npz') != info['sha256']: raise ValueError('Dataset changed after lock')
        for name_, value in info['frames'].items():
            if digest(root/name/'scenes'/name_) != value: raise ValueError('Evaluation frame changed after lock')
    result_dir=root/'results';result_dir.mkdir(exist_ok=False)
    dump(result_dir/'environment.json',{"python":sys.version,"platform":platform.platform(),
        "packages":{p:version(p) for p in ['numpy','scipy','scikit-learn','pytest','joblib','websockets','pyserial']},
        "code_sha":subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        "working_diff":subprocess.check_output(['git','diff'],text=True),
        "feature_names":FEATURE_NAMES,"settings":SETTINGS,
        "source_sha256":{str(f.relative_to(Path(__file__).parent)):digest(f) for f in Path(__file__).parent.rglob("*.py")}})
    train={name:load_clusters(root/(name+'-train')) for name in ('baseline','candidate')}
    test={name:load_clusters(root/('eval-'+name)) for name in ('standard','challenge')}
    tr,te=split_by_scene(train['baseline']['scene_ids'],.2,0)
    test_scenes=np.unique(train['baseline']['scene_ids'][te])
    # Dataset identity is (generator seed, scene id), not local numeric scene id alone.
    assert len({SETTINGS['training_seed'],SETTINGS['standard_seed'],SETTINGS['challenge_seed']})==3
    dump(result_dir/'split.json',{"training_seed":SETTINGS['training_seed'],"validation_scene_ids":test_scenes.tolist(),
        "evaluation_seeds":[SETTINGS['standard_seed'],SETTINGS['challenge_seed']],"unit":"independent generated scene/layout"})
    metrics={};predictions={}
    for kind,d in train.items():
        is_test=np.isin(d['scene_ids'],test_scenes);is_train=~is_test
        assert set(d['scene_ids'][is_train]).isdisjoint(d['scene_ids'][is_test])
        for seed in SETTINGS['forest_seeds']:
            key=f'{kind}-s{seed}';print('Training '+key,flush=True)
            clf=RandomForestClassifier(**SETTINGS['forest'],random_state=seed)
            start=time.perf_counter();clf.fit(d['features'][is_train],d['labels'][is_train]);elapsed=time.perf_counter()-start
            joblib.dump(clf,result_dir/(key+'.joblib'))
            validation={k:v[is_test] for k,v in d.items()}
            metrics[key]={"train_clusters":int(is_train.sum()),"validation_clusters":int(is_test.sum()),"fit_seconds":elapsed,
                "train_accuracy":float(clf.score(d['features'][is_train],d['labels'][is_train])),
                "feature_importance":dict(zip(FEATURE_NAMES,clf.feature_importances_.tolist())),
                "validation":scores(clf,validation)[0],"evaluation":{}}
            for name,ds in test.items():
                value,pred=scores(clf,ds);metrics[key]['evaluation'][name]=value;predictions[(key,name)]=pred
            if seed==0:
                classifier=ForestClassifier(result_dir/(key+'.joblib'))
                for name in test:
                    frames=[SonarFrame.load(f) for f in sorted((root/('eval-'+name)/'scenes').glob('*.npz'))]
                    outcomes=object_outcomes(frames,classifier,'person')
                    summary=summarize(outcomes); n=len(outcomes);correct=sum(r['outcome']=='correct' for r in outcomes)
                    metrics[key]['evaluation'][name]['person_end_to_end']={"correct":correct,"total":n,"recall":correct/n if n else None,"breakdown":summary}
                    dump(result_dir/(key+'-'+name+'-person-outcomes.json'),outcomes)
                    if name=='standard':
                        detections,_=detect_frame(frames[0],classifier)
                        document=frame_detections_dict(frames[0],detections,classifier.name)
                        sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'websocket-bridge'))
                        from sonar_bridge.protocol import encode_sonar_frame
                        wire=json.loads(encode_sonar_frame(frames[0],0,document))
                        metrics[key]['wire_compatibility']={"protocol_version":wire['protocol_version'],"source":wire['source'],
                            "acquisition_source":wire['acquisition_source'],"detection_format":document['format_version']}
                        dump(result_dir/(key+'-detections-sample.json'),document)
            print(key+' '+json.dumps({n:round(v['report']['macro avg']['f1-score'],4) for n,v in metrics[key]['evaluation'].items()}),flush=True)
    comparison={}
    for name,ds in test.items():
        comparison[name]={}
        for metric in ('accuracy','macro_f1'):
            def value(kind,seed):
                m=metrics[f'{kind}-s{seed}']['evaluation'][name]
                return m['accuracy'] if metric=='accuracy' else m['report']['macro avg']['f1-score']
            a=[value('baseline',s) for s in SETTINGS['forest_seeds']];b=[value('candidate',s) for s in SETTINGS['forest_seeds']]
            comparison[name][metric]={"baseline":a,"candidate":b,"baseline_mean":float(np.mean(a)),"candidate_mean":float(np.mean(b)),"delta":float(np.mean(b)-np.mean(a))}
        a=predictions[('baseline-s0',name)];b=predictions[('candidate-s0',name)];truth=ds['labels']
        cases=[]
        for i in np.flatnonzero(a!=b):
            cases.append({"scene_id":int(ds['scene_ids'][i]),"env":str(ds['env'][i]),"purity":float(ds['purity'][i]),
                "true":CLASSES[int(truth[i])],"baseline":CLASSES[int(a[i])],"candidate":CLASSES[int(b[i])]})
        dump(result_dir/(name+'-disagreements.json'),cases)
        comparison[name]['baseline_correct_candidate_wrong']=int(((a==truth)&(b!=truth)).sum())
        comparison[name]['baseline_wrong_candidate_correct']=int(((a!=truth)&(b==truth)).sum())
        # Paired bootstrap over whole scenes, preserving correlated clusters within a room.
        scenes=np.unique(ds['scene_ids']);scene_deltas=[float(((b==truth).astype(float)-(a==truth))[ds['scene_ids']==s].sum()) for s in scenes]
        counts=[int((ds['scene_ids']==s).sum()) for s in scenes];rng=np.random.default_rng(8001)
        ix=rng.integers(0,len(scenes),size=(1000,len(scenes)))
        draws=np.asarray(scene_deltas)[ix].sum(axis=1)/np.asarray(counts)[ix].sum(axis=1)
        comparison[name]['paired_accuracy_delta_scene_bootstrap_95pct']=np.quantile(draws,[.025,.975]).tolist()
    standard=comparison['standard']['macro_f1']['delta'];challenge=comparison['challenge']['macro_f1']['delta']
    a=metrics['baseline-s0']['evaluation']['standard']['person_end_to_end']['recall'];b=metrics['candidate-s0']['evaluation']['standard']['person_end_to_end']['recall']
    decision='ADOPT CANDIDATE' if standard>=-.01 and challenge>=.02 and b-a>=-.02 else 'RETAIN BASELINE'
    output={"settings":SETTINGS,"classes":list(CLASSES.values()),"metrics":metrics,"comparison":comparison,
        "decision":decision,"production_inference_changed":False,"used_by_live_viewer":False,
        "limitations":["Synthetic clusters condition on successful extraction; see person end-to-end diagnostics for misses.",
            "No real array sonar captures or existing production weights were available.","HC-SR04 scalar distances cannot supply this 3D cluster feature model."]}
    dump(result_dir/'metrics.json',output)
    print(json.dumps({"decision":decision,"comparison":comparison}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--stage',choices=['prepare','evaluate','all'],default='all');a=parser.parse_args()
    if a.stage in ('prepare','all'): prepare(a.root)
    if a.stage in ('evaluate','all'): evaluate(a.root)

if __name__=='__main__': main()
