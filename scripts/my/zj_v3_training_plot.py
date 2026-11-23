"""Render comparable training episode lengths and disturbance curriculum."""
import re
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parents[3]
fig, axes = plt.subplots(2,1,figsize=(9,6),sharex=True,layout='constrained')
for filename,label,color in [('zj_v3_stand_train.log','Initial rewards','#aaaaaa'),
                              ('zj_v3_stand_train_v2.log','Stronger upright reward + PD initial policy','#157baf')]:
    s = (root / filename).read_text(encoding='utf-8',errors='replace')
    rows = []
    for block in re.split(r'Learning iteration\s+',s)[1:]:
        iteration = re.match(r'(\d+)',block)
        length = re.search(r'Mean episode length:\s+([\d.]+)',block)
        ramp = re.search(r'Push/curriculum:\s+([\d.]+)',block)
        if iteration and length and ramp:
            rows.append((int(iteration[1]),float(length[1])*.02,float(ramp[1])))
    if rows:
        axes[0].plot([r[0] for r in rows],[r[1] for r in rows],label=label,color=color)
        axes[1].plot([r[0] for r in rows],[r[2]*100 for r in rows],color=color)
axes[0].axhline(20,color='#777777',ls='--',lw=.8)
axes[0].set(ylabel='Mean training episode (s)',ylim=(0,21),title='ZJ V3 standing: training progress (not held-out evaluation)')
axes[0].legend(fontsize=8,loc='lower right')
axes[1].set(ylabel='Push curriculum (%)',xlabel='PPO iteration',ylim=(-2,102))
for ax in axes:
    ax.grid(alpha=.2)
    ax.spines[['top','right']].set_visible(False)
fig.savefig(root / 'zj_v3_runs/standing_training.png',dpi=160)
print(root / 'zj_v3_runs/standing_training.png')
