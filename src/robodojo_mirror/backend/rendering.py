from copy import deepcopy
import numpy as np
import carb.settings
from pxr import UsdGeom
from ..launch import ZERO_DELAY
from .usd import ROOT


def dispatcher_time():
    import omni.graph.core as og
    node=og.get_node_by_path('/Render/PostProcess/SDGPipeline/PostProcessDispatcher')
    if not node: return None
    denominator=node.get_attribute('outputs:referenceTimeDenominator').get()
    if not denominator: return None
    return float(node.get_attribute('outputs:referenceTimeNumerator').get())/float(denominator)

def synchronized_render(env, limit):
    settings=carb.settings.get_settings()
    for key,expected in ZERO_DELAY.items():
        actual=str(settings.get(key)).lower()
        if actual != expected:
            raise RuntimeError('Launch with configure_launcher(args) before AppLauncher; missing '+key)
    previous=dispatcher_time()

    delivered=0
    for _ in range(limit):
        env.render()
        current=dispatcher_time()
        if previous is not None and current is not None and current != previous:
            delivered += 1
        previous=current
        if delivered >= 1: return
    raise RuntimeError('Camera dispatcher did not deliver current frames; no stale RGB returned')

def composite(base, reflected, mask):
    if base.shape != reflected.shape or mask.shape != base.shape[:2]:
        raise ValueError('Incompatible RGB/mask shapes')
    from scipy.ndimage import distance_transform_edt
    alpha=np.clip(distance_transform_edt(mask)/1.5,0.,1.)[:,:,None]
    result=np.rint(base*(1-alpha)+reflected*alpha).astype(np.uint8)
    if not np.array_equal(result[~mask],base[~mask]):
        raise RuntimeError('Compositing changed nonmirror pixels')
    return result


def tile_ids(data, env_id, tiled_resolution, image_shape):

    width,height=map(int,tiled_resolution)
    h,w=image_shape[:2]
    if width%w or height%h or not 0<=env_id<(width//w)*(height//h):
        raise ValueError('Segmentation tile geometry does not match native RGB')
    ids=np.asarray(data['data']).reshape(height,width)
    row,col=divmod(env_id,width//w)
    return ids[row*h:(row+1)*h,col*w:(col+1)*w]

class MirrorRenderer:
    def __init__(self,env,config,scenes):
        self.env,self.config,self.scenes=env,config,scenes
        self.settings=carb.settings.get_settings()
        self.annotations={}; self.camera_indices={}
        self.stats=dict(captures=0,mirror_passes=0,mask_pixels={})
        self.stage=None
        self.warmed=False

        if config.condition not in ('single_mirror','dual_mirror','mirror_tabletop'): return
        import omni.replicator.core as rep
        import omni.usd
        self.stage=omni.usd.get_context().get_stage()
        try:
            for j,view in enumerate(env.capture_manager.tiled_cameras):
                annotation=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',
                    init_params={'colorize':False},device='cpu')
                annotation.attach([view._render_product_path])
                self.annotations[j]=annotation
                for env_id in range(env.num_envs):
                    name=env.camera_manager.camera_names[env_id][j]
                    self.camera_indices[env_id,name]=j
        except BaseException:
            self.close()
            raise

    def _mask(self,env_id,name,rgb,data):
        j=self.camera_indices[env_id,name]
        camera=self.env.camera_manager.cameras[env_id][j]
        view=self.env.capture_manager.tiled_cameras[j]
        ids=tile_ids(data,env_id,view.tiled_resolution,rgb.shape)
        labels=data['info']['idToLabels']
        scene=self.scenes[env_id]
        if 'tabletop' not in scene:
            selected=[int(k) for k,v in labels.items() if f'{ROOT}/env_{env_id}/' in str(v)
                      and '/ReflectingSurface' in str(v)]
            return np.isin(ids,selected)
        table=scene['tabletop']
        selected=[int(k) for k,v in labels.items() if table['table_prim'] in str(v)]
        prim=self.stage.GetPrimAtPath(str(camera.prim_path))
        usd_camera=UsdGeom.Camera(prim)
        if usd_camera.GetProjectionAttr().Get() != 'perspective':
            raise ValueError('Tabletop masking requires a perspective camera')

        if (usd_camera.GetHorizontalApertureOffsetAttr().Get() or
                usd_camera.GetVerticalApertureOffsetAttr().Get()):
            raise ValueError('Shifted camera principal points need a mask adapter')
        matrix=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim))
        height,width=rgb.shape[:2]
        fx=usd_camera.GetFocalLengthAttr().Get()*width/usd_camera.GetHorizontalApertureAttr().Get()
        fy=usd_camera.GetFocalLengthAttr().Get()*height/usd_camera.GetVerticalApertureAttr().Get()
        yy,xx=np.mgrid[:height,:width]
        rays=np.stack(((xx+.5-width/2)/fx,-(yy+.5-height/2)/fy,-np.ones((height,width))),-1)@matrix[:3,:3]
        origin=matrix[3,:3]
        with np.errstate(divide='ignore',invalid='ignore'):
            distance=(table['top_z']-origin[2])/rays[:,:,2]
            hits=origin+rays*distance[:,:,None]
        lo,hi=np.asarray(table['xy_bounds'])
        return (np.isin(ids,selected)&(distance>0)&(rays[:,:,2]<0)&
                np.all((hits[:,:,:2]>=lo)&(hits[:,:,:2]<=hi),axis=2))

    def capture(self,read_native,env_ids):
        if self.warmed:
            return self._capture(read_native,env_ids)


        import omni.usd
        keys=('/rtx/materialDb/syncLoads', '/rtx/hydra/materialSyncLoads',
              '/omni.kit.plugin/syncUsdLoads')
        previous={k:self.settings.get(k) for k in keys}
        try:
            for key in keys: self.settings.set(key,True)
            for index in range(max(5,self.config.capture_pass_limit)):
                self._capture(read_native,env_ids)
                loading=omni.usd.get_context().get_stage_loading_status()[2]
                if index >= 4 and loading == 0:
                    result=self._capture(read_native,env_ids)
                    self.warmed=True
                    return result
            raise RuntimeError('Scene assets still loading; refusing an unready first image')
        finally:
            for key,value in previous.items():
                if value is None: self.settings.destroy_item(key)
                else: self.settings.set(key,value)

    def _capture(self,read_native,env_ids):

        before=self.env.sim.sim.current_time
        synchronized_render(self.env,self.config.capture_pass_limit)
        base=deepcopy(read_native(env_idx_list=env_ids))
        segment={j:a.get_data() for j,a in self.annotations.items()}

        for _ in range(8):
            if all(np.asarray(d['data']).size for d in segment.values()): break
            synchronized_render(self.env,self.config.capture_pass_limit)
            base=deepcopy(read_native(env_idx_list=env_ids))
            segment={j:a.get_data() for j,a in self.annotations.items()}
        if not all(np.asarray(d['data']).size for d in segment.values()):
            raise RuntimeError('Segmentation unavailable after initialization')
        masks={}
        for env_id in env_ids:
            for name,camera in base[env_id].get('vision',{}).items():
                if 'color' in camera and (env_id,name) in self.camera_indices:
                    masks[env_id,name]=self._mask(env_id,name,np.asarray(camera['color']),segment[self.camera_indices[env_id,name]])
        if any(mask.any() for mask in masks.values()):
            quality={'/rtx/rendermode':'PathTracing',
                     '/rtx/pathtracing/spp':self.config.mirror_spp,
                     '/rtx/pathtracing/clampSpp':self.config.mirror_spp,
                     '/rtx/pathtracing/totalSpp':0,
                     '/rtx/pathtracing/maxBounces':16,
                     '/rtx/pathtracing/maxSpecularAndTransmissionBounces':16,
                     '/rtx/pathtracing/optixDenoiser/enabled':True,
                     '/rtx/pathtracing/optixDenoiser/temporalMode/enabled':False,
                     '/rtx/pathtracing/optixDenoiser/blendFactor':0.,
                     '/rtx/pathtracing/cached/enabled':True,
                     '/rtx/resetPtAccumOnAnimTimeChange':True}
            previous={k:self.settings.get(k) for k in quality}
            try:
                for k,v in quality.items(): self.settings.set(k,v)
                synchronized_render(self.env,self.config.capture_pass_limit)
                high=deepcopy(read_native(env_idx_list=env_ids))
                for (env_id,name),mask in masks.items():
                    target=base[env_id]['vision'][name]
                    target['color']=composite(np.asarray(target['color']),
                        np.asarray(high[env_id]['vision'][name]['color']),mask)
                self.stats['mirror_passes']+=1
            finally:
                for k,v in previous.items():
                    if v is None: self.settings.destroy_item(k)
                    else: self.settings.set(k,v)
        if self.env.sim.sim.current_time != before:
            raise RuntimeError('Rendering advanced simulation time')
        self.stats['captures']+=1
        self.stats['mask_pixels']={f'{i}/{n}':int(m.sum()) for (i,n),m in masks.items()}
        return base

    def close(self):
        for annotation in self.annotations.values(): annotation.detach()
        self.annotations.clear()
        self.camera_indices.clear()
