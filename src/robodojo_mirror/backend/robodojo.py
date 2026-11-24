from dataclasses import asdict
from itertools import product
import numpy as np
from pxr import UsdGeom
from .usd import ROOT, mesh_points, install_panels, install_tabletop, restore
from ..scenes.geometry import panel_specs, is_tabletop_object
from ..tasks.selection import SKIPS

STORES = ('_rigid_and_dynamic_objects','_geometry_objects','_articulation_objects',
          '_garment_objects','_fluid_objects')

def host(value):
    return value.detach().cpu().numpy() if hasattr(value,'detach') else np.asarray(value)

def object_entries(env, env_id):
    for store in STORES:
        for name,obj in getattr(env.scene_manager,store,[])[env_id].items():
            path = str(getattr(obj,'usd_prim_path',None) or obj.prim_path)
            if 'camera_stand' not in path:
                yield store,name,obj,path

class RoboDojoBackend:
    def __init__(self, env, config):
        import omni.usd
        self.env,self.config=env,config
        self.stage=omni.usd.get_context().get_stage()
        if self.stage.GetPrimAtPath(ROOT):
            raise RuntimeError('This stage already has an active RoboDojo-Mirror owner')
        self.undo=[]; self.scenes={}; self.renderer=None; self.contacts=None

    def _points(self, store,obj,path):
        if store == '_fluid_objects':
            positions=host(obj.get_particle_positions()[0])
            matrix=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(obj.point_instancer.GetPrim()))
            world=positions @ matrix[:3,:3]+matrix[3,:3]
            radius=float(obj.particle_system.GetParticleContactOffsetAttr().Get() or .0025)
            return np.concatenate([world+np.asarray(delta)*radius for delta in product((-1,1),repeat=3)])
        return mesh_points(self.stage,path)

    def prepare(self):
        import omni.physx
        self.clear()
        condition=self.config.condition
        task=getattr(self.env,'task_name',type(self.env).__name__)
        reason=SKIPS.get((task,condition))
        if reason: raise ValueError(f'{task}/{condition} is skipped by protocol: {reason}')
        try:
            for env_id in range(self.env.num_envs):
                scene=dict(condition=condition,placement_revision=self.config.revision,
                           config=asdict(self.config),panels=[],colliders={})
                self.scenes[env_id]=scene
                if condition == 'no_mirror': continue
                table=self.env.scene_manager._tables[env_id]
                if table is None: raise ValueError(f'env {env_id}: no official table')
                table_path=str(table.prim_path)
                table_points=mesh_points(self.stage,table_path)
                low,high=table_points.min(0),table_points.max(0)

                transform=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath(table_path)))
                axes=transform[:3,:3]
                if np.max(np.abs(axes-np.diag(np.diag(axes)))) > 1e-6:
                    raise ValueError('Rotated tables need an explicit coordinate-frame adapter')
                if condition == 'mirror_tabletop':
                    scene['tabletop']=install_tabletop(self.stage,table_path,env_id,self.undo)
                    scene['colliders']={'tabletop':table_path}
                    continue
                parts=[]
                selected,excluded=[],[]
                for store,name,obj,path in object_entries(self.env,env_id):
                    points=self._points(store,obj,path)
                    if is_tabletop_object(points,low,high):
                        parts.append(points); selected.append(path)
                    else:
                        excluded.append(path)
                scene['placement_objects']=dict(included=selected,excluded=excluded,
                    rule='initial tabletop footprint overlap and bottom at or above tabletop (1 cm tolerance)')
                if not parts: raise ValueError('No tabletop task object geometry for mirror placement')
                objects=np.concatenate(parts)
                env_root=self.stage.GetPrimAtPath(f'/World/envs/env_{env_id}')
                robots=[mesh_points(self.stage,str(p.GetPath())) for p in env_root.GetChildren()
                        if p.GetName().startswith('robot') and p.GetName()[5:].isdigit()]
                if not robots: raise ValueError('No robot mesh roots')
                robots=np.concatenate(robots)
                specs=panel_specs(((low+high)/2).tolist(),(high-low).tolist(),robots,objects,self.config)
                for camera in self.env.camera_manager.cameras[env_id]:
                    prim=self.stage.GetPrimAtPath(str(camera.prim_path))
                    origin=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim).ExtractTranslation())
                    if any(np.dot(origin-np.asarray(s['seam']),s['normal']) >= 0 for s in specs):
                        raise ValueError(f'Camera is behind a mirror plane: {camera.prim_path}')
                scene['panels']=specs
                scene['colliders']=install_panels(self.stage,env_id,specs,condition.endswith('mirror'))
            omni.physx.get_physx_simulation_interface().flush_changes()
            if self.config.record_contacts and condition != 'no_mirror':
                from .contacts import PhysicsContacts
                self.contacts=PhysicsContacts(self.env,self.scenes)
            return self.scenes
        except BaseException:
            self.clear()
            raise

    def capture(self, read_native, env_ids):
        if self.renderer is None:
            from .rendering import MirrorRenderer
            self.renderer=MirrorRenderer(self.env,self.config,self.scenes)
        return self.renderer.capture(read_native,env_ids)

    def after_physics_step(self):
        if self.contacts: self.contacts.sample()

    def metadata(self):
        return dict(scenes=self.scenes,
                    rendering=self.renderer.stats if self.renderer else {'captures':0,'mirror_passes':0},
                    contacts=self.contacts.summary() if self.contacts else None)

    def clear(self):
        if self.renderer:
            self.renderer.close(); self.renderer=None
        if self.contacts:
            self.contacts.close(); self.contacts=None
        restore(self.stage,self.undo)
        self.scenes={}
        import omni.physx
        omni.physx.get_physx_simulation_interface().flush_changes()

    close=clear
