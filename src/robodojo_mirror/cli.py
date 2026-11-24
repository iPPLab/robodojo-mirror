import argparse
import ast
import json
from pathlib import Path
from .tasks.selection import discover_tasks, select_tasks, exclusion_reason, load_tasks

def inspect_source(root):
    root=Path(root)
    contracts={
        'env/environment/base_env.py': {'BaseEnv':('launch_sim','reset','render','sim_step')},
        'env/observation_manager/obs_manager.py': {'ObsManager':('get_obs','render_for_capture')},
        'env/camera_manager/capture/tiled_capture_manager.py': {'TiledCaptureManager':('step','reset')},
        'env/camera_manager/capture/camera_view.py': {'CameraView':('_clean_up_tiled_sensor',)},
    }
    checks=[]
    for relative,classes in contracts.items():
        file=root/relative
        if not file.is_file():
            checks.append(dict(file=relative,ok=False,reason='missing file')); continue
        tree=ast.parse(file.read_text())
        for name,methods in classes.items():
            cls=next((n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name==name),None)
            found={} if cls is None else {n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
            missing=sorted(set(methods)-found.keys())
            checks.append(dict(file=relative,class_name=name,ok=not missing,missing=missing,
                signatures={key:ast.unparse(found[key].args) for key in methods if key in found}))
    return dict(kind='read-only source interface inspection; not a simulator test',checks=checks,
                ok=all(check['ok'] for check in checks))


def main(argv=None):
    parser=argparse.ArgumentParser(description="CPU-only task selection and source-interface inspection.")
    sub=parser.add_subparsers(dest='command',required=True)
    cmd=sub.add_parser('list-tasks')
    cmd.add_argument('--robodojo-root',type=Path,required=True)
    group=cmd.add_mutually_exclusive_group()
    group.add_argument('--task-set',choices=('default','all'),default='default')
    group.add_argument('--tasks',nargs='+')
    group.add_argument('--tasks-file',type=Path)
    cmd.add_argument('--show-excluded',action='store_true')
    check=sub.add_parser('check-source')
    check.add_argument('--robodojo-root',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='check-source':
            report=inspect_source(args.robodojo_root)
        else:
            available=discover_tasks(args.robodojo_root)
            chosen=load_tasks(args.tasks_file) if args.tasks_file else args.tasks
            selected=select_tasks(available,args.task_set,chosen)
            report=dict(tasks=selected,count=len(selected))
            if args.show_excluded:
                report['all_set_exclusions']={t:exclusion_reason(t) for t in available if exclusion_reason(t)}
        print(json.dumps(report,indent=2,allow_nan=False))
        return 1 if args.command=='check-source' and not report['ok'] else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,f'{exc}\n')

if __name__=='__main__':
    raise SystemExit(main())
