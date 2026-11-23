"""Simulator-independent parameter validation for training and a future frontend."""
import json
import math
import os
from pathlib import Path
import jsonschema


def validate_settings(p):
    schema = json.loads(Path(__file__).with_name('stand_parameters.schema.json').read_text(encoding='utf-8'))
    jsonschema.Draft202012Validator(schema).validate(p)
    def check_finite(v):
        if isinstance(v, dict):
            for child in v.values():
                check_finite(child)
        elif isinstance(v, list):
            for child in v:
                check_finite(child)
        elif isinstance(v, float) and not math.isfinite(v):
            raise ValueError('Non-finite parameter')
    check_finite(p)
    for key in ('interval_s', 'duration_s', 'horizontal_force_n', 'vertical_force_n'):
        lo, hi = p['disturbance'][key]
        if lo > hi:
            raise ValueError(f'Invalid disturbance range: {key}')
    if not (p['termination']['minimum_height_m'] < p['robot']['height_m'] < p['robot']['spawn_height_m'] + .1):
        raise ValueError('Invalid robot height settings')
    return p


def load_settings():
    path = Path(os.environ.get('ZJV3_STAND_CONFIG', Path(__file__).with_name('stand_parameters.json')))
    return validate_settings(json.loads(path.read_text(encoding='utf-8')))
