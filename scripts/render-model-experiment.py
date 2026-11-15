"""Render measured confusion counts; no training or synthetic generation."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metrics',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
a=parser.parse_args()
if a.out.exists(): parser.error('Refusing to overwrite a report image')
d=json.loads(a.metrics.read_text())
fig,axes=plt.subplots(2,2,figsize=(12,10),layout='constrained')
maximum=max(max(max(row) for row in d['metrics'][model+'-s0']['evaluation'][cohort]['confusion_matrix']) for cohort in ['standard','challenge'] for model in ['baseline','candidate'])
for row,cohort in enumerate(['standard','challenge']):
    for col,model in enumerate(['baseline','candidate']):
        score=d['metrics'][model+'-s0']['evaluation'][cohort]
        matrix=np.array(score['confusion_matrix']);ax=axes[row,col]
        im=ax.imshow(matrix,cmap='Blues',vmin=0,vmax=maximum)
        ax.set_xticks(range(6),d['classes'],rotation=35,ha='right');ax.set_yticks(range(6),d['classes'])
        ax.set_xlabel('Predicted cluster class');ax.set_ylabel('True cluster class')
        ax.set_title(f"{cohort.title()} / {model}: {score['n']} clusters")
        for i in range(6):
            for j in range(6): ax.text(j,i,str(matrix[i,j]),ha='center',va='center',color='white' if matrix[i,j]>.6*maximum else 'black',fontsize=9)
fig.colorbar(im,ax=axes.ravel().tolist(),label='Number of held-out synthetic clusters',shrink=.8)
fig.suptitle('Sonar random forest: unchanged held-out synthetic scenes, forest seed 0')
fig.supxlabel('Rows = ground truth; unextracted objects excluded. See report for person end-to-end misses.')
a.out.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(a.out,dpi=140);plt.close(fig)
print(a.out)
