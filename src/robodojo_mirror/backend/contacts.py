import numpy as np
from pxr import Usd, UsdPhysics, PhysxSchema
from .robodojo import host
from ..contacts import ContactLedger

class PhysicsContacts:
    def __init__(self,env,scenes):
        import omni.physx, omni.usd
        from isaacsim.core.simulation_manager import SimulationManager
        self.env,self.scenes=env,scenes
        self.views={}; self.ledgers={}; self.undo=[]
        self.capacity=16384
        stage=omni.usd.get_context().get_stage()
        self.stage=stage
        try:
            for env_id,scene in scenes.items():
                paths=[]
                for prim in Usd.PrimRange(stage.GetPrimAtPath(f'/World/envs/env_{env_id}')):
                    path=str(prim.GetPath())
                    if '/robot' not in path or not prim.HasAPI(UsdPhysics.RigidBodyAPI): continue
                    had_api=prim.HasAPI(PhysxSchema.PhysxContactReportAPI)
                    api=PhysxSchema.PhysxContactReportAPI.Apply(prim)
                    attr=api.GetThresholdAttr()
                    authored=attr.HasAuthoredValueOpinion(); value=attr.Get()
                    self.undo.append((path,had_api,authored,value))
                    api.CreateThresholdAttr().Set(0.)
                    paths.append(path)
                if not paths: raise RuntimeError('No robot bodies for contact reports')
                omni.physx.get_physx_simulation_interface().flush_changes()
                simulation=SimulationManager.get_physics_sim_view()
                self.ledgers[env_id]=ContactLedger(scene['colliders'])
                for name,collider in scene['colliders'].items():
                    view=simulation.create_rigid_contact_view(paths,
                        filter_patterns=[[collider] for _ in paths],max_contact_data_count=self.capacity)
                    if view.sensor_count != len(paths) or view.filter_count != 1:
                        raise RuntimeError('PhysX contact view registration mismatch')
                    self.views[env_id,name]=view
        except BaseException:
            self.close()
            raise

    def sample(self):
        active={i:set() for i in self.ledgers}
        dt=float(self.env.sim.sim.get_physics_dt())
        for (env_id,name),view in self.views.items():
            forces,positions,normals,_,counts,starts=view.get_contact_data(dt=dt)
            counts,starts=host(counts),host(starts)
            if int(counts.sum()) >= self.capacity:
                raise RuntimeError('Contact buffer full; refusing incomplete contact statistics')
            for sensor in range(view.sensor_count):
                count=int(counts[sensor,0]); start=int(starts[sensor,0])
                if not count: continue
                selected=slice(start,start+count)
                keep=host(forces[selected]).reshape(-1)>1e-6
                if name == 'tabletop':
                    points=host(positions[selected]); normal=host(normals[selected])
                    top=self.scenes[env_id]['tabletop']['top_z']
                    keep &= (np.abs(points[:,2]-top)<=.005)&(np.abs(normal[:,2])>=.9)
                if keep.any(): active[env_id].add(name)
        controls=getattr(self.env,'take_action_cnt',None)
        for env_id,ledger in self.ledgers.items():
            control=int(controls[env_id]) if controls is not None else self.env.mirror.control_step
            ledger.update(active[env_id],control)

    def summary(self):
        return dict(source='PhysX rigid contact view',normal_force_threshold_N=1e-6,
                    environments={i:ledger.summary() for i,ledger in self.ledgers.items()})

    def close(self):
        self.views.clear()
        for path,had_api,authored,value in reversed(self.undo):
            prim=self.stage.GetPrimAtPath(path)
            if not prim: continue
            api=PhysxSchema.PhysxContactReportAPI(prim)
            if authored: api.GetThresholdAttr().Set(value)
            else: api.GetThresholdAttr().Clear()
            if not had_api: prim.RemoveAPI(PhysxSchema.PhysxContactReportAPI)
        self.undo.clear()
