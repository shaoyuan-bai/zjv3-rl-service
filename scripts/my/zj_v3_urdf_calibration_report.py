"""Generate a first-pass calibration report for the ZJ V3 URDF.

This checks what can be verified from the URDF alone. Physical calibration
still requires measurements from the real robot (zero offsets, actuator
limits, delays, and measured inertias).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET


DEFAULT_URDF = r"D:\xwechat_files\wxid_dw65v2dasu9u22_4b64\msg\file\2026-07\ZJ_V3_URDF_V1_1\ZJ_V3_URDF_V1_1_isaac.urdf"


def attr_float(element: ET.Element | None, name: str, default: float = 0.0) -> float:
    if element is None:
        return default
    try:
        return float(element.attrib.get(name, default))
    except (TypeError, ValueError):
        return default


def vec3(text: str | None) -> list[float]:
    values = (text or "0 0 0").replace(",", " ").split()
    return [float(values[i]) if i < len(values) else 0.0 for i in range(3)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urdf", default=DEFAULT_URDF)
    parser.add_argument("--output", default=r"E:\isaac-lab\zj_v3_urdf_calibration_report.json")
    args = parser.parse_args()

    root = ET.parse(args.urdf).getroot()
    links = []
    zero_mass_links = []
    total_mass = 0.0
    for link in root.findall("link"):
        inertial = link.find("inertial")
        mass_node = inertial.find("mass") if inertial is not None else None
        mass = attr_float(mass_node, "value")
        total_mass += mass
        inertia_node = inertial.find("inertia") if inertial is not None else None
        inertia = {
            key: attr_float(inertia_node, key)
            for key in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")
        }
        if mass <= 0.0:
            zero_mass_links.append(link.attrib.get("name", ""))
        links.append(
            {
                "name": link.attrib.get("name", ""),
                "mass_kg": mass,
                "inertial_origin_xyz_m": vec3(
                    (inertial.find("origin") if inertial is not None else None).attrib.get("xyz")
                    if inertial is not None and inertial.find("origin") is not None
                    else None
                ),
                "inertia": inertia,
            }
        )

    joints = []
    unsupported_limits = []
    for joint in root.findall("joint"):
        joint_type = joint.attrib.get("type", "")
        limit = joint.find("limit")
        limit_data = None
        if limit is not None:
            limit_data = {
                key: attr_float(limit, key)
                for key in ("lower", "upper", "effort", "velocity")
                if key in limit.attrib
            }
        elif joint_type not in {"fixed", "continuous"}:
            unsupported_limits.append(joint.attrib.get("name", ""))
        axis = joint.find("axis")
        origin = joint.find("origin")
        joints.append(
            {
                "name": joint.attrib.get("name", ""),
                "type": joint_type,
                "parent": (joint.find("parent").attrib.get("link", "") if joint.find("parent") is not None else ""),
                "child": (joint.find("child").attrib.get("link", "") if joint.find("child") is not None else ""),
                "axis": vec3(axis.attrib.get("xyz") if axis is not None else None),
                "origin_xyz_m": vec3(origin.attrib.get("xyz") if origin is not None else None),
                "origin_rpy_rad": vec3(origin.attrib.get("rpy") if origin is not None else None),
                "limit": limit_data,
            }
        )

    movable = [j for j in joints if j["type"] != "fixed"]
    revolute = [j for j in movable if j["type"] in {"revolute", "continuous"}]
    report = {
        "urdf": os.path.abspath(args.urdf),
        "robot_name": root.attrib.get("name", ""),
        "link_count": len(links),
        "joint_count": len(joints),
        "movable_joint_count": len(movable),
        "revolute_or_continuous_joint_count": len(revolute),
        "total_mass_kg": total_mass,
        "mass_sanity": math.isfinite(total_mass) and total_mass > 0.0,
        "zero_or_missing_mass_links": zero_mass_links,
        "joints_missing_limits": unsupported_limits,
        "links": links,
        "joints": joints,
        "calibration_items_requiring_real_robot": [
            "joint_zero_offsets_and_signs",
            "motor_torque_and_velocity_limits",
            "joint_damping_and_friction",
            "imu_orientation_and_bias",
            "contact_friction_and_restitution",
            "control_loop_delay_and_action_latency",
            "measured_link_mass_and_inertia_validation",
        ],
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: report[k] for k in (
        "robot_name", "link_count", "joint_count", "movable_joint_count",
        "revolute_or_continuous_joint_count", "total_mass_kg", "zero_or_missing_mass_links",
        "joints_missing_limits",
    )} | {"output": os.path.abspath(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
