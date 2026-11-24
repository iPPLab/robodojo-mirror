from itertools import chain
from math import atan2, cos, dist, fsum, isfinite, sin, sqrt

def corrected_dual_specs(table_center, table_size, robot_points, object_points, revision):

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


def panel_specs(table_center, table_size, robot_points, object_points, config):
    robots, objects = list(robot_points), list(object_points)
    revision = dict(panel_height_m=config.height_m, panel_thickness_m=config.thickness_m,
                    outward_offset_m=config.clearance_m)

    for points in (robots, objects):
        if not points:
            raise ValueError("Robot and object geometry must be nonempty")
    for point in chain(robots, objects, [table_center, table_size]):
        if len(point) != 3 or not all(isfinite(v) for v in point):
            raise ValueError("Geometry must contain finite XYZ triples")
    if not all(v > 0 for v in table_size):
        raise ValueError("Table dimensions must be positive")
    top = table_center[2] + table_size[2] / 2

    if config.condition in ('dual_mirror', 'dual_panel'):
        return corrected_dual_specs(table_center, table_size, robots, objects, revision)

    revision['panel_height_m'] = max(config.height_m,
        max(p[2] for p in chain(robots, objects)) - top + config.clearance_m)
    if config.condition not in ('single_mirror', 'single_panel'):
        return []
    support_y = max(p[1] for p in chain(robots, objects))
    requested_y = support_y + config.clearance_m
    far_edge_y = table_center[1] + table_size[1] / 2
    rear = min(requested_y, far_edge_y)
    tx, width = table_center[0], table_size[0]
    height, thickness = revision['panel_height_m'], config.thickness_m
    return [dict(name='single', seam=[tx-width/2, rear, top],
                 endpoint=[tx+width/2, rear, top], normal=[0,1,0],
                 center=[tx,rear+thickness/2,top+height/2],
                 half_extent=[width/2,thickness/2,height/2],
                 quaternion_xyzw=[0,0,0,1], clearance_m=rear-support_y,
                 requested_clearance_m=config.clearance_m,
                 far_edge_y_m=far_edge_y,
                 clamped_to_far_edge=requested_y > far_edge_y)]


def is_tabletop_object(points, table_low, table_high, tolerance=.01):

    points=list(points)
    if not points:
        return False
    low=[min(p[i] for p in points) for i in range(3)]
    high=[max(p[i] for p in points) for i in range(3)]
    return (low[2] >= table_high[2]-tolerance and
            all(high[i] >= table_low[i] and low[i] <= table_high[i] for i in (0,1)))
