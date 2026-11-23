import argparse
from isaaclab.app import AppLauncher
parser = argparse.ArgumentParser()
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
launcher = AppLauncher(args)
try:
    from pxr import Usd, UsdPhysics
    import isaaclab, torch, rsl_rl
    p = r'D:\xwechat_files\wxid_dw65v2dasu9u22_4b64\msg\file\2026-07\ZJ_V3_URDF_V1_1\ZJ_V3_URDF_V1_1_isaac.usd'
    s = Usd.Stage.Open(p)
    print('PROBE', isaaclab.__file__, torch.__version__, flush=True)
    print('DEFAULT', s.GetDefaultPrim().GetPath(), flush=True)
    print('ROOTS', [(str(x.GetPath()), x.GetTypeName()) for x in s.GetPseudoRoot().GetChildren()], flush=True)
    print('ARTIC', [str(x.GetPath()) for x in s.Traverse() if x.HasAPI(UsdPhysics.ArticulationRootAPI)], flush=True)
finally:
    launcher.app.close()
