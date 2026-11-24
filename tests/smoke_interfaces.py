from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from robodojo_mirror import MirrorConfig, attach, configure_launcher
from robodojo_mirror.scenes.geometry import panel_specs
from robodojo_mirror.tasks.selection import DEFAULT_TASKS, select_tasks

class Simulation:
    def __init__(self): self.current_time=0; self.renders=0
    def step(self,render=True):
        self.current_time+=1
        if render: self.render()
    def render(self): self.renders+=1

class Observations:
    def __init__(self,env):
        self.env=env; self.camera_manager=object(); self.capture_manager=object()
    def get_obs(self,env_idx_list=None):
        return {0:{'state':{'time':self.env.sim.sim.current_time},
                   'vision':{'camera':{'color':'current-frame'}} if self.capture_manager else {}}}
    def render_for_capture(self): self.env.render()

class FakeEnv:
    def __init__(self):
        self.num_envs=1; self.sim=None; self.obs_manager=Observations(self)
        self.capture_manager=SimpleNamespace(**{key:[] for key in ('tiled_cameras',
            'tiled_render_products','annotator','annotator_type','annotator_device','camera_prim_paths')},
            _output_buffers={})
    def launch_sim(self): self.sim=SimpleNamespace(sim=Simulation())
    def reset(self):
        if self.sim is None: self.launch_sim()
        self.sim.sim.step(); self.render()
        self.obs_manager.render_for_capture(); self.obs_manager.get_obs()
    def render(self): self.sim.sim.render()
    def step(self): self.sim.sim.step()
    def close(self): pass

class FakeBackend:
    def __init__(self,env,config): self.env=env; self.captures=0; self.steps=0
    def prepare(self): pass
    def clear(self): pass
    def close(self): pass
    def after_physics_step(self): self.steps+=1
    def capture(self,reader,env_ids):
        self.env.render(); self.captures+=1
        return reader(env_idx_list=env_ids)
    def metadata(self): return {'captures':self.captures,'steps':self.steps}


def main():
    config=MirrorConfig(condition='double_mirror')
    assert config.condition=='dual_mirror'
    assert config.height_m==.8 and MirrorConfig(condition='dual_panel').height_m==.8
    assert MirrorConfig(condition='single_mirror').height_m==1.3
    assert MirrorConfig(condition='dual_mirror',height_m=1.1).height_m==1.1
    tall_specs=panel_specs([0,0,.4],[2,1,.1],[(0,-.3,2.0)],[(.2,0,.5)],config)
    assert all(abs(2*s['half_extent'][2]-.8)<1e-10 for s in tall_specs)
    args=configure_launcher(SimpleNamespace(kit_args=''))
    assert args.headless and 'waitIdle=true' in args.kit_args
    available=list(DEFAULT_TASKS)+['make_kong','play_tic_tac_toe','push_T','push_T_random',
        'organize_table','match_and_pick_from_conveyor','pick_from_conveyor_by_image']
    assert select_tasks(available)==list(DEFAULT_TASKS)
    assert select_tasks(available,'all')==sorted([*DEFAULT_TASKS,'push_T'])
    assert select_tasks(available,tasks=['make_kong'])==['make_kong']
    specs=panel_specs([0,0,.4],[2,1,.1],[(0,-.3,.6)],[(.2,0,.5)],config)
    assert len(specs)==2 and all(abs(s['clearance_m']-.05)<1e-10 for s in specs)

    for condition in ('single_mirror','single_panel'):
        single=MirrorConfig(condition=condition)
        for object_y,expected_y,expected_gap,clamped in (
                (2.3,2.35,.05,False),(2.48,2.5,.02,True),(2.45,2.5,.05,False)):
            spec=panel_specs([0,2,.4],[2,1,.1],[(0,2,.6)],[(0,object_y,.5)],single)[0]
            assert abs(spec['seam'][1]-expected_y)<1e-10
            assert abs(spec['clearance_m']-expected_gap)<1e-10
            assert spec['clamped_to_far_edge']==clamped
        assert single.revision=='single_normal_5cm_table_edge_v1'
    env=attach(FakeEnv(),config,backend_factory=FakeBackend)
    env.reset()
    assert env.sim.sim.renders==0
    env.step()
    assert env.sim.sim.renders==0 and env.mirror.backend.steps==1
    now=env.sim.sim.current_time
    observation=env.obs_manager.get_obs()
    assert observation[0]['vision'] and env.sim.sim.renders==1 and env.sim.sim.current_time==now
    assert env.mirror.get_state()[0]['vision']=={} and env.sim.sim.renders==1
    env.reset(); assert env.sim.sim.renders==1
    env.close()
    env.sim.sim.step(); assert env.sim.sim.renders==2
    state=attach(FakeEnv(),MirrorConfig(capture_rgb=False),backend_factory=FakeBackend)
    state.reset(); state.step()
    assert state.obs_manager.get_obs()[0]['vision']=={} and state.sim.sim.renders==0
    assert state.mirror.capture_rgb()[0]['vision'] and state.sim.sim.renders==1
    state.close()
    assert 'numpy' not in sys.modules and 'omni' not in sys.modules
    print('PASS: public imports/config, task selection, geometry return contract, delayed environment hooks, state-only and explicit RGB flow; no simulator used.')

if __name__=='__main__': main()
