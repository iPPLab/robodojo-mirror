from .config import MirrorConfig

class MirrorController:
    def __init__(self,env,config,backend_factory=None):
        if hasattr(env,'mirror'): raise ValueError('Environment already has a mirror controller')
        if not hasattr(env,'obs_manager'):
            raise TypeError('Use a RoboDojo evaluation environment with obs_manager')
        self.env,self.config=env,config
        self.backend_factory=backend_factory
        self.backend=None
        self.ready=False; self.resetting=False; self.capturing=False
        self.control_step=0; self.physics_steps=0; self.last_metadata=None
        self.saved=[]
        self.closed=False
        self.bound_sim=None
        self.native_read=self._hook(env.obs_manager,'get_obs',self._get_obs)
        self._hook(env.obs_manager,'render_for_capture',lambda *a,**k: None)
        self.native_reset=self._hook(env,'reset',self._reset)
        self.native_step=self._hook(env,'step',self._step)
        self.native_close=self._hook(env,'close',self._close_env)
        self.native_launch=self._hook(env,'launch_sim',self._launch)


        for name in ('_stream_vision','save_video'):
            if hasattr(env,name): self._hook(env,name,lambda *a,**k: None)
        self._bind_sim()

    def _bind_sim(self):
        if self.env.sim is None: return
        sim=self.env.sim.sim
        if self.bound_sim is sim: return
        if self.bound_sim is not None:
            raise RuntimeError('Replacing the SimulationContext requires a new environment')
        if getattr(sim,'_robodojo_mirror_owner',None) is not None:
            raise RuntimeError('SimulationContext already has a mirror controller')
        sim._robodojo_mirror_owner=self
        self.bound_sim=sim
        self._hook(sim,'step',self._physics_step)
        self._hook(sim,'render',self._render)

    def _launch(self,*args,**kwargs):
        result=self.native_launch(*args,**kwargs)
        self._bind_sim()
        return result

    def _release_capture_products(self):


        manager=self.env.capture_manager


        released=set()
        for camera in manager.tiled_cameras:
            product=camera._render_product
            for annotation in camera._annotators.values():
                annotation.detach([camera._render_product_path])
            camera._annotators.clear()
            if product is not None and id(product) not in released:
                product.destroy()
                released.add(id(product))
            camera._render_product=None
            camera._render_product_path=None
            camera._tiled_render_product=None
        for product in manager.tiled_render_products:
            if product is not None and id(product) not in released:
                product.destroy()
                released.add(id(product))
        for name in ('tiled_cameras','tiled_render_products','annotator','annotator_type',
                     'annotator_device','camera_prim_paths'):
            getattr(manager,name).clear()
        manager._output_buffers.clear()

    def _reset(self,*args,**kwargs):
        self.begin_reset()
        try:
            if self.env.sim is not None: self._release_capture_products()
            result=self.native_reset(*args,**kwargs)
            if result is not None:
                raise TypeError('This adapter expects native RoboDojo reset() -> None')
            self.finish_reset()
            return result
        except BaseException:
            self.resetting=False; self.ready=False
            if self.backend: self.backend.clear()
            raise

    def _step(self,*args,**kwargs):
        self.control_step+=1
        return self.native_step(*args,**kwargs)

    def _close_env(self,*args,**kwargs):
        try:
            self.close()
        finally:
            self.native_close(*args,**kwargs)

    def _hook(self,obj,name,replacement):
        original=getattr(obj,name)
        owned=name in vars(obj)
        self.saved.append((obj,name,original,owned))
        setattr(obj,name,replacement)
        return original

    def _original(self,obj,name):
        return next(original for owner,key,original,_ in self.saved if owner is obj and key==name)

    def _physics_step(self,*args,**kwargs):
        if self.capturing:
            raise RuntimeError('Physics may not advance during camera capture')

        if args:
            args=(False,)+args[1:]
            kwargs.pop('render',None)
        else:
            kwargs['render']=False
        result=self._original(self.env.sim.sim,'step')(*args,**kwargs)
        self.physics_steps+=1
        if self.ready and self.backend:
            self.backend.after_physics_step()
        return result

    def _render(self,*args,**kwargs):
        if self.capturing:
            return self._original(self.env.sim.sim,'render')(*args,**kwargs)

        return None

    def begin_reset(self):
        if self.capturing: raise RuntimeError('Cannot reset during capture')
        self.ready=False; self.resetting=True
        self.control_step=0; self.physics_steps=0
        if self.backend:
            self.last_metadata=self.backend.metadata()
            self.backend.clear()

    def finish_reset(self):
        if self.backend is None:
            factory=self.backend_factory
            if factory is None:
                from .backend.robodojo import RoboDojoBackend
                factory=RoboDojoBackend
            self.backend=factory(self.env,self.config)
        try:
            self.backend.prepare()
            self.ready=True
        finally:
            self.resetting=False

    def _state_obs(self,env_idx_list=None):
        manager=self.env.obs_manager
        capture,camera=manager.capture_manager,manager.camera_manager
        try:
            manager.capture_manager=None; manager.camera_manager=None
            return self.native_read(env_idx_list=env_idx_list)
        finally:
            manager.capture_manager=capture; manager.camera_manager=camera

    def _get_obs(self,env_idx_list=None):
        if self.resetting or not self.config.capture_rgb:
            return self._state_obs(env_idx_list)
        return self.capture_rgb(env_idx_list)

    def capture_rgb(self,env_idx_list=None):
        if not self.ready: raise RuntimeError('Complete env.reset() before requesting RGB')
        if self.capturing: raise RuntimeError('Recursive or concurrent capture is unsupported')
        env_ids=list(range(self.env.num_envs)) if env_idx_list is None else list(env_idx_list)
        if not env_ids or len(set(env_ids))!=len(env_ids) or any(type(i) is not int or not 0<=i<self.env.num_envs for i in env_ids):
            raise ValueError('Invalid environment IDs')
        self.capturing=True
        try:

            return self.backend.capture(self.native_read,env_ids)
        finally:
            self.capturing=False

    def get_state(self,env_idx_list=None):
        return self._state_obs(env_idx_list)

    def metadata(self):
        return self.backend.metadata() if self.backend else None

    def close(self):
        if self.closed: return
        try:
            if self.backend:
                self.last_metadata=self.backend.metadata()
                self.backend.close()
        finally:
            for obj,name,original,owned in reversed(self.saved):
                if owned: setattr(obj,name,original)
                else: delattr(obj,name)
            self.saved.clear(); self.ready=False; self.closed=True
            if self.bound_sim is not None and getattr(self.bound_sim,'_robodojo_mirror_owner',None) is self:
                delattr(self.bound_sim,'_robodojo_mirror_owner')

def attach(env, config=None, *, backend_factory=None):

    env.mirror=MirrorController(env,config or MirrorConfig(),backend_factory)
    return env


def wrap_env_class(env_class, config=None, *, backend_factory=None):
    config=config or MirrorConfig()
    class MirrorEnv(env_class):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            attach(self,config,backend_factory=backend_factory)
    MirrorEnv.__name__='Mirror'+env_class.__name__
    return MirrorEnv
