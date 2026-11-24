import math
import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

ROOT = '/World/RoboDojoMirror'

def mesh_points(stage, path):
    prim = stage.GetPrimAtPath(path)
    if not prim:
        raise ValueError(f'Missing geometry prim: {path}')
    cache, parts = UsdGeom.XformCache(), []
    for child in Usd.PrimRange(prim):
        if child.IsA(UsdGeom.Mesh) and UsdGeom.Imageable(child).ComputeVisibility() != 'invisible':
            raw = np.asarray(UsdGeom.Mesh(child).GetPointsAttr().Get() or [], dtype=float)
            if len(raw):
                matrix = np.asarray(cache.GetLocalToWorldTransform(child))
                parts.append(raw @ matrix[:3,:3] + matrix[3,:3])
    if not parts:
        bound = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default','render']).ComputeWorldBound(prim).ComputeAlignedRange()
        if bound.IsEmpty():
            raise ValueError(f'Empty geometry: {path}')
        parts = [np.asarray([bound.GetCorner(i) for i in range(8)])]
    result = np.concatenate(parts)
    if not np.isfinite(result).all():
        raise ValueError(f'Nonfinite geometry: {path}')
    return result

def material(stage, path, *, mirror=False):
    mat = UsdShade.Material.Define(stage,path)
    shader = UsdShade.Shader.Define(stage,path+'/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*((1.,)*3 if mirror else (.85,)*3)))

    shader.CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(1.)
    shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(1. if mirror else 0.)
    shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(0. if mirror else .65)
    shader.CreateOutput('surface',Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    return mat

def install_panels(stage, env_id, specs, reflective):
    prefix = f'{ROOT}/env_{env_id}'
    backing = material(stage,prefix+'/Materials/Backing')
    front = material(stage,prefix+'/Materials/Front',mirror=reflective)
    paths = {}
    for spec in specs:
        path = prefix+'/'+spec['name']
        parent = UsdGeom.Xform.Define(stage,path)
        xform = UsdGeom.Xformable(parent)
        xform.AddTranslateOp().Set(Gf.Vec3d(*spec['center']))
        qx,qy,qz,qw = spec['quaternion_xyzw']
        xform.AddOrientOp().Set(Gf.Quatf(qw,Gf.Vec3f(qx,qy,qz)))
        width,thickness,height = [2*x for x in spec['half_extent']]
        body = UsdGeom.Cube.Define(stage,path+'/Body')
        body.CreateSizeAttr(1.)
        UsdGeom.Xformable(body).AddScaleOp().Set(Gf.Vec3f(width,thickness,height))

        UsdPhysics.CollisionAPI.Apply(body.GetPrim()).CreateCollisionEnabledAttr(True)
        UsdGeom.Imageable(body).MakeInvisible()
        shell=UsdGeom.Mesh.Define(stage,path+'/Backing')
        x,y,z=width/2,thickness/2,height/2
        shell.CreatePointsAttr([(-x,-y,-z),(x,-y,-z),(x,-y,z),(-x,-y,z),
                                (-x,y,-z),(x,y,-z),(x,y,z),(-x,y,z)])
        shell.CreateFaceVertexCountsAttr([4]*5)
        shell.CreateFaceVertexIndicesAttr([4,7,6,5, 0,4,5,1, 3,2,6,7, 0,3,7,4, 1,5,6,2])
        shell.CreateSubdivisionSchemeAttr('none'); shell.CreateDoubleSidedAttr(True)
        UsdShade.MaterialBindingAPI.Apply(shell.GetPrim()).Bind(backing)
        face = UsdGeom.Mesh.Define(stage,path+'/ReflectingSurface' if reflective else path+'/PanelSurface')
        y = -thickness/2
        face.CreatePointsAttr([(-width/2,y,-height/2),(width/2,y,-height/2),
                               (width/2,y,height/2),(-width/2,y,height/2)])
        face.CreateFaceVertexCountsAttr([4]); face.CreateFaceVertexIndicesAttr([0,1,2,3])
        face.CreateSubdivisionSchemeAttr('none'); face.CreateDoubleSidedAttr(False)

        UsdShade.MaterialBindingAPI.Apply(face.GetPrim()).Bind(front)
        paths[spec['name']] = str(body.GetPath())
    return paths

def install_tabletop(stage, table_path, env_id, undo):
    prim = stage.GetPrimAtPath(table_path)
    mesh = UsdGeom.Mesh(prim)
    if not mesh:
        raise ValueError('Table must be a mesh; refusing to replace its geometry')
    matrix = np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim))
    raw = np.asarray(mesh.GetPointsAttr().Get(),dtype=float)
    world = raw @ matrix[:3,:3]+matrix[3,:3]
    top = float(world[:,2].max())
    indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get())
    selected, offset = [], 0
    for i,count in enumerate(mesh.GetFaceVertexCountsAttr().Get()):
        polygon = world[indices[offset:offset+count]]; offset += count
        if np.max(np.abs(polygon[:,2]-top)) < 1e-5:
            selected.append(i)
    if not selected:
        raise ValueError('Cannot identify horizontal tabletop faces')
    subset_path = table_path+'/RoboDojoMirrorTop'
    if stage.GetPrimAtPath(subset_path):
        raise ValueError(f'Existing owned subset: {subset_path}')
    mat = material(stage,f'{ROOT}/env_{env_id}/Materials/Tabletop',mirror=True)
    family_attr=prim.GetAttribute('subsetFamily:materialBind:familyType')
    family_state=(bool(family_attr), bool(family_attr and family_attr.HasAuthoredValueOpinion()),
                  family_attr.Get() if family_attr else None)
    undo.append(('family',table_path,family_state))
    subset = UsdGeom.Subset.CreateGeomSubset(mesh,'RoboDojoMirrorTop',UsdGeom.Tokens.face,
        selected,'materialBind',UsdGeom.Tokens.nonOverlapping)
    undo.append(('prim',str(subset.GetPath()),None))
    ancestor = prim
    while ancestor and not ancestor.IsPseudoRoot():
        for rel in ancestor.GetRelationships():
            if rel.GetName() in ('material:binding','material:binding:preview','material:binding:full'):
                old = rel.GetMetadata('bindMaterialAs')
                if old == UsdShade.Tokens.strongerThanDescendants:
                    undo.append(('strength',str(rel.GetPath()),old))
                    UsdShade.MaterialBindingAPI.SetMaterialBindingStrength(rel,UsdShade.Tokens.weakerThanDescendants)
        ancestor = ancestor.GetParent()
    UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(mat)
    effective,_ = UsdShade.MaterialBindingAPI(subset.GetPrim()).ComputeBoundMaterial()
    if effective.GetPath() != mat.GetPath():
        raise RuntimeError('Original binding overrides the tabletop mirror')
    return dict(table_prim=table_path,top_face_subset=subset_path,top_z=top,
        xy_bounds=[world[:,:2].min(0).tolist(),world[:,:2].max(0).tolist()],
        top_face_count=len(selected),original_geometry_and_collider_preserved=True)

def restore(stage, undo):
    for kind,path,value in reversed(undo):
        if kind == 'prim':
            if stage.GetPrimAtPath(path): stage.RemovePrim(path)
        elif kind == 'family':
            prim=stage.GetPrimAtPath(path)
            if prim:
                existed,authored,old=value
                if not existed: prim.RemoveProperty('subsetFamily:materialBind:familyType')
                elif authored: prim.GetAttribute('subsetFamily:materialBind:familyType').Set(old)
                else: prim.GetAttribute('subsetFamily:materialBind:familyType').Clear()
        else:
            relation=stage.GetRelationshipAtPath(path)
            if relation: relation.SetMetadata('bindMaterialAs',value)
    undo.clear()
    if stage.GetPrimAtPath(ROOT): stage.RemovePrim(ROOT)
