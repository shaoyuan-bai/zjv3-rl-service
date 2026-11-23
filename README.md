# ZJ V3 RL service overlay

This public repository contains the local ZJ V3 quadruped task, its URDF provenance, training scripts, and the HTTP training service overlay.

It applies to an Isaac Lab 2.3.2 / Isaac Sim 5.1.0 checkout at base commit `80094be3245aa5c8376a7464d29cb4412ea518f5`.

The robot source is `assets/robots/zj_v3/source/ZJ_V3_URDF_V1_1_isaac.urdf`. The generated flattened `robot.usd` is intentionally excluded because it exceeds GitHub's normal per-file limit. Regenerate it on the target machine with Isaac Sim using `scripts/my/zj_v3_prepare_asset.py`, or transfer it separately.

This repository contains no Conda environment, Isaac Sim runtime, CUDA libraries, runtime logs, checkpoints, API tokens, or PM01 humanoid code.

## Linux setup

```bash
git clone <this-repository-url>
cd zjv3-rl-service
python -m pip install -r integrations/rl_service/requirements.txt
export ZJV3_USD_PATH=/opt/robots/zj_v3/robot.usd
export RL_SERVICE_CONFIG=$PWD/rl_service.json
python -m integrations.rl_service serve
```

The base Isaac Lab checkout must be installed separately. Put the generated `robot.usd` at the configured path, or update `rl_service.json`.
