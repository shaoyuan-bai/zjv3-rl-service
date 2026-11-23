"""Make a local USD deployment asset and prove it has no external dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
launcher = AppLauncher(args)
try:
    from pxr import Usd, UsdUtils, UsdShade, Sdf, Gf
    source = args.source.resolve()
    target = args.output.resolve()
    if target.exists():
        raise FileExistsError(target)
    stage = Usd.Stage.Open(str(source))
    if stage is None:
        raise RuntimeError('Cannot open source USD')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Flatten layer references; inline meshes retain original physics/visual data.
    stage = Usd.Stage.Open(stage.Flatten())
    while True:
        instances = [p for p in stage.TraverseAll() if p.IsInstanceable()]
        if not instances:
            break
        for prim in instances:
            prim.SetInstanceable(False)
    materials = [p.GetPath() for p in stage.Traverse() if p.IsA(UsdShade.Material)]
    # Replace runtime-specific MDL shaders by standard USD preview shaders.
    shaders = [p.GetPath() for p in stage.Traverse() if p.IsA(UsdShade.Shader)]
    for path in shaders:
        stage.RemovePrim(path)
    for path in materials:
        material = UsdShade.Material(stage.GetPrimAtPath(path))
        for name in ('outputs:mdl:surface', 'outputs:mdl:volume', 'outputs:mdl:displacement'):
            material.GetPrim().RemoveProperty(name)
        shader = UsdShade.Shader.Define(stage, path.AppendChild('PortableSurface'))
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.75, .75, .78))
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(.5)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    layer = stage.Flatten()
    def clear_mdl(path):
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.AttributeSpec) and spec.typeName == Sdf.ValueTypeNames.Asset and isinstance(spec.default, Sdf.AssetPath) and spec.default.path.endswith('.mdl'):
            spec.default = Sdf.AssetPath('')
    layer.Traverse(Sdf.Path.absoluteRootPath, clear_mdl)
    layer.Export(str(target))
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(target))
    print('ZJV3_DEPENDENCIES', len(layers), assets, unresolved, flush=True)
    if assets or unresolved or len(layers) != 1:
        target.unlink()
        raise RuntimeError(f'Not self-contained: assets={assets}, unresolved={unresolved}, layers={len(layers)}')
    report = {'source_filename': source.name, 'deployment_filename': target.name, 'layer_count': len(layers), 'external_assets': list(assets), 'unresolved': list(unresolved), 'material_conversion': 'standard UsdPreviewSurface; neutral gray', 'sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()}
    target.with_suffix('.manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('ZJV3_ASSET_READY', report, flush=True)
finally:
    launcher.app.close()
