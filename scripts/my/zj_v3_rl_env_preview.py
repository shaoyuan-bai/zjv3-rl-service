"""Preview scene for ZJ V3 quadruped RL training.

Loads the converted robot USD, adds a bounded training arena and obstacles,
then keeps the simulator open for visual inspection.
"""

import argparse
import os
import traceback

from isaacsim import SimulationApp


parser = argparse.ArgumentParser(description="Preview the ZJ V3 RL arena.")
parser.add_argument(
    "--robot-usd",
    default=r"D:\xwechat_files\wxid_dw65v2dasu9u22_4b64\msg\file\2026-07\ZJ_V3_URDF_V1_1\ZJ_V3_URDF_V1_1_isaac.usd",
)
parser.add_argument(
    "--output-usd",
    default=r"E:\isaac-lab\zj_v3_rl_arena_preview.usd",
)
args = parser.parse_args()

app = SimulationApp(
    {
        "headless": False,
        "renderer": "RaytracedLighting",
        "width": 1600,
        "height": 1000,
        "sync_loads": True,
    }
)


def add_box(stage, path, center, size, color=(0.35, 0.35, 0.38), collision=True):
    from pxr import Gf, Sdf, UsdGeom, UsdPhysics

    cube = UsdGeom.Cube.Define(stage, Sdf.Path(path))
    cube.CreateSizeAttr(1.0)
    xform = UsdGeom.Xformable(cube.GetPrim())
    xform.AddTranslateOp().Set(Gf.Vec3d(*center))
    xform.AddScaleOp().Set(Gf.Vec3f(*size))
    # Display color keeps the layout readable in the preview.
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    if collision:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube


def add_cylinder(stage, path, center, radius, height, color=(0.65, 0.32, 0.10)):
    from pxr import Gf, Sdf, UsdGeom, UsdPhysics

    cyl = UsdGeom.Cylinder.Define(stage, Sdf.Path(path))
    cyl.CreateRadiusAttr(radius)
    cyl.CreateHeightAttr(height)
    cyl.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdGeom.Xformable(cyl.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(*center))
    UsdPhysics.CollisionAPI.Apply(cyl.GetPrim())
    return cyl


try:
    import omni.usd
    from isaacsim.core.utils.stage import is_stage_loading
    from isaacsim.core.utils.viewports import set_camera_view
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdLux

    if not os.path.isfile(args.robot_usd):
        raise FileNotFoundError(args.robot_usd)

    context = omni.usd.get_context()
    if not context.open_stage(args.robot_usd):
        raise RuntimeError(f"Unable to open robot USD: {args.robot_usd}")
    for _ in range(10):
        app.update()
    while is_stage_loading():
        app.update()

    stage = context.get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    # Find the imported robot root and place it at the center of the arena.
    robot_candidates = []
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            robot_candidates.append(prim)
    if robot_candidates:
        robot_root = robot_candidates[0]
        robot_xform = UsdGeom.Xformable(robot_root)
        if not robot_xform.GetOrderedXformOps():
            robot_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))

    # Physics scene and a generous floor.  The robot USD may already contain
    # a physics scene; reusing the existing one avoids duplicate scenes.
    physics_scene = None
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Scene):
            physics_scene = UsdPhysics.Scene(prim)
            break
    if physics_scene is None:
        physics_scene = UsdPhysics.Scene.Define(stage, Sdf.Path("/World/PhysicsScene"))
    physics_scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(0.0, 0.0, -1.0))
    physics_scene.CreateGravityMagnitudeAttr().Set(9.81)

    arena = stage.DefinePrim("/World/ZJ_V3_RL_Arena", "Xform")
    # Robot feet in the supplied USD are approximately z=-0.636 m in its
    # straight-leg pose, so this floor supports the robot at the origin.
    add_box(stage, "/World/ZJ_V3_RL_Arena/Floor", (0.0, 0.0, -0.70), (8.0, 6.0, 0.10), (0.18, 0.20, 0.22))

    # Four solid boundary walls: 8 m x 6 m arena, 1.2 m high.
    wall_color = (0.12, 0.25, 0.42)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Wall_N", (0.0, 3.0, 0.0), (8.0, 0.15, 1.4), wall_color)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Wall_S", (0.0, -3.0, 0.0), (8.0, 0.15, 1.4), wall_color)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Wall_E", (4.0, 0.0, 0.0), (0.15, 6.0, 1.4), wall_color)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Wall_W", (-4.0, 0.0, 0.0), (0.15, 6.0, 1.4), wall_color)

    # Low blocks and posts provide simple contact/avoidance challenges while
    # leaving a clear central area around the initial standing pose.
    obstacle_color = (0.80, 0.30, 0.08)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Obstacle_Block_A", (1.45, 1.25, -0.25), (0.85, 0.85, 0.90), obstacle_color)
    add_box(stage, "/World/ZJ_V3_RL_Arena/Obstacle_Block_B", (-1.55, 1.30, -0.35), (0.70, 0.70, 0.70), (0.90, 0.55, 0.08))
    add_box(stage, "/World/ZJ_V3_RL_Arena/Obstacle_Bar", (0.0, -1.65, -0.48), (2.0, 0.35, 0.45), (0.08, 0.55, 0.88))
    add_cylinder(stage, "/World/ZJ_V3_RL_Arena/Obstacle_Cylinder_A", (2.50, -0.55, -0.30), 0.38, 0.80)
    add_cylinder(stage, "/World/ZJ_V3_RL_Arena/Obstacle_Cylinder_B", (-2.55, -0.80, -0.42), 0.28, 0.56, (0.60, 0.15, 0.10))

    # Soft neutral dome light and a key light for a clear preview.
    dome = UsdLux.DomeLight.Define(stage, Sdf.Path("/World/ZJ_V3_RL_Arena/DomeLight"))
    dome.CreateIntensityAttr(700.0)
    dome.CreateColorAttr(Gf.Vec3f(0.75, 0.80, 0.90))
    key = UsdLux.DistantLight.Define(stage, Sdf.Path("/World/ZJ_V3_RL_Arena/KeyLight"))
    key.CreateIntensityAttr(1200.0)
    key.CreateAngleAttr(0.5)
    UsdGeom.Xformable(key.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3f(-35.0, 25.0, -35.0))

    set_camera_view(
        eye=[8.6, -9.0, 6.8],
        target=[0.0, 0.0, -0.15],
        camera_prim_path="/OmniverseKit_Persp",
    )
    # Save one viewport image so the scene can be reviewed without opening
    # the full simulator window.
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    screenshot_path = os.path.splitext(args.output_usd)[0] + ".png"
    capture_future = capture_viewport_to_file(get_active_viewport(), file_path=screenshot_path)
    for _ in range(120):
        app.update()
        if hasattr(capture_future, "done") and capture_future.done():
            break
    os.makedirs(os.path.dirname(args.output_usd), exist_ok=True)
    stage.GetRootLayer().Export(args.output_usd)
    print(f"Saved preview arena: {args.output_usd}", flush=True)
    print("Arena: 8m x 6m, four walls, five obstacles, ZJ V3 at center.", flush=True)

    # Keep physics paused for a stable inspection pose.
    for _ in range(30):
        app.update()
    while app.is_running():
        app.update()
except Exception:
    traceback.print_exc()
    while app.is_running():
        app.update()
finally:
    app.close()
