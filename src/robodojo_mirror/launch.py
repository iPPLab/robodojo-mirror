ZERO_DELAY = {'/app/updateOrder/checkForHydraRenderComplete':'1000',
              '/app/renderer/waitIdle':'true', '/app/hydraEngine/waitIdle':'true'}

def configure_launcher(args):
    current=getattr(args,'kit_args',None) or ''
    import shlex
    tokens=shlex.split(current)
    for key,value in ZERO_DELAY.items():
        prefix='--'+key+'='
        present=[t[len(prefix):] for t in tokens if t.startswith(prefix)]
        if present and any(v.lower()!=value for v in present):
            raise ValueError(f'Conflicting frame synchronization setting: {key}')
        if not present: current += ' '+prefix+value
    args.kit_args=current.strip()


    args.headless=True
    args.enable_cameras=True
    return args
