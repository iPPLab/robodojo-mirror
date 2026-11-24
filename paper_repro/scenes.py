"""Scene selection and portable geometry for the revised dual-panel placement."""

from itertools import chain
from math import atan2, cos, dist, fsum, isfinite, sin, sqrt


def scene_settings(protocol, policy, condition, revision=None):
    controls = protocol["controls"]
    if condition not in protocol["conditions"]:
        if condition not in controls or policy not in protocol["control_policies"]:
            raise ValueError(f"Condition {condition!r} is unavailable for {policy}")
    geometry = controls.get(condition, condition)
    if revision is not None and condition not in revision["eligible_conditions"]:
        raise ValueError(f"The revised geometry does not apply to {condition}")
    material = {
        "no_mirror": "original",
        "mirror_tabletop": "reflective_tabletop",
    }.get(condition, "nonreflective" if condition in controls else "reflective")
    return {
        "geometry": geometry,
        "material": material,
        "placement_revision": (revision or protocol)["protocol_revision"],
        "static_vertical_colliders": geometry in {"single_mirror", "dual_mirror"},
    }


def corrected_dual_specs(table_center, table_size, robot_points, object_points, revision):
    """Return two slabs from world XYZ mesh points in a common environment frame.

    The tabletop is axis-aligned. Its center is the center of the table slab.
    Each slab extends outward from its reflective face by its thickness.
    """
    robot_points, object_points = list(robot_points), list(object_points)
    if not robot_points or not object_points:
        raise ValueError("Dual placement requires robot and task-object meshes")
    points = [tuple(point) for point in chain(robot_points, object_points)]
    table_center, table_size = tuple(table_center), tuple(table_size)
    for point in chain(points, [table_center, table_size]):
        if len(point) != 3 or not all(isfinite(value) for value in point):
            raise ValueError("Geometry inputs must be finite XYZ triples")
    tx, _, tz = table_center
    width, depth, table_thickness = table_size
    height = revision["panel_height_m"]
    thickness = revision["panel_thickness_m"]
    offset = revision["outward_offset_m"]
    if not all(isfinite(value) and value > 0 for value in
               (width, depth, table_thickness, height, thickness, offset)):
        raise ValueError("Table and panel dimensions and offset must be positive")

    top = tz + table_thickness / 2
    margin = sqrt(2) * offset
    left = max(y - x for x, y, _ in points) + margin
    right = max(y + x for x, y, _ in points) + margin
    seam = ((right - left) / 2, (left + right) / 2, top)
    x_min, x_max = tx - width / 2, tx + width / 2
    if not x_min < seam[0] < x_max:
        raise ValueError(f"Mirror seam falls outside the tabletop side lines: {seam}")

    specs = []
    segments = (
        ("left", (x_min, left + x_min, top), ((-1 / sqrt(2)), 1 / sqrt(2), 0)),
        ("right", (x_max, right - x_max, top), (1 / sqrt(2), 1 / sqrt(2), 0)),
    )
    for name, endpoint, normal in segments:
        yaw = atan2(-normal[0], normal[1])
        length = dist(endpoint, seam)
        center = [(a + b) / 2 + axis * thickness / 2
                  for a, b, axis in zip(seam, endpoint, normal)]
        center[2] += height / 2
        clearance = min(fsum((start - value) * axis
                             for start, value, axis in zip(seam, point, normal))
                        for point in points)
        specs.append({
            "name": name,
            "seam": seam,
            "endpoint": endpoint,
            "center": center,
            "normal": normal,
            "half_extent": [length / 2, thickness / 2, height / 2],
            "quaternion_xyzw": [0, 0, sin(yaw / 2), cos(yaw / 2)],
            "clearance_m": clearance,
        })
    return specs
