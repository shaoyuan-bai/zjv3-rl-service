"""Check exported TorchScript and ONNX numerical agreement without Isaac Sim."""
import argparse
import json
from pathlib import Path
import numpy as np
import onnx
from onnx.reference import ReferenceEvaluator
import torch

parser = argparse.ArgumentParser()
parser.add_argument('run', type=Path)
args = parser.parse_args()
model = onnx.load(args.run / 'exported/policy.onnx')
onnx.checker.check_model(model)
reference = ReferenceEvaluator(model)
script = torch.jit.load(str(args.run / 'exported/policy.pt'), map_location='cpu').eval()
input_dim = model.graph.input[0].type.tensor_type.shape.dim[-1].dim_value
rng = np.random.default_rng(42)
max_error = 0.
for _ in range(8):
    x = rng.normal(0., .2, (1,input_dim)).astype(np.float32)
    with torch.inference_mode():
        expected = script(torch.from_numpy(x)).numpy()
    actual = reference.run(None, {model.graph.input[0].name:x})[0]
    np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-4)
    max_error = max(max_error, float(np.abs(actual-expected).max()))
    assert actual.shape == (1,16) and np.isfinite(actual).all()
result = {'input_dim':input_dim,'output_dim':16,'onnx_valid':True,'samples':8,'max_absolute_error':max_error}
(args.run / 'export_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
