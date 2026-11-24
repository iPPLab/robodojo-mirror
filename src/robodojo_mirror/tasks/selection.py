from pathlib import Path
import json

DEFAULT_TASKS = ("cover_blocks", "fold_clothes", "general_pickup", "press_by_number",
                 "insert_tubes", "swap_T", "stack_blocks", "stack_bowls")
EXCLUDED = {
    "match_and_pick_from_conveyor": "conveyor",
    "pick_from_conveyor_by_image": "conveyor",
    "make_kong": "opponent", "play_tic_tac_toe": "opponent",
    "organize_table": "excluded by protocol",
}
SKIPS = {('match_and_pick_from_conveyor', 'mirror_tabletop'): 'no official tabletop',
         ('put_bottles_into_dustbin', 'dual_mirror'): 'protocol exception',
         ('put_bottles_into_dustbin', 'dual_panel'): 'matched dual geometry exception'}

def discover_tasks(robodojo_root):
    directory = Path(robodojo_root) / 'task' / 'RoboDojo' / 'tasks'
    if not directory.is_dir():
        raise ValueError(f"Missing RoboDojo tasks directory: {directory}")
    return sorted(p.stem for p in directory.glob('*.py') if not p.name.startswith('_'))

def exclusion_reason(task):
    return EXCLUDED.get(task) or ('random task' if 'random' in task.lower() else None)

def select_tasks(available, task_set='default', tasks=None):
    available = set(available)
    if tasks is not None:
        if task_set != 'default':
            raise ValueError('Custom tasks and --task-set are mutually exclusive')
        chosen = list(tasks)
    elif task_set == 'default':
        chosen = list(DEFAULT_TASKS)
    elif task_set == 'all':
        chosen = sorted(t for t in available if not exclusion_reason(t))
    else:
        raise ValueError(f'Unknown task set: {task_set}')
    if not chosen or any(not isinstance(t, str) or not t for t in chosen):
        raise ValueError('Task list must contain nonempty task names')
    if len(chosen) != len(set(chosen)):
        raise ValueError('Duplicate tasks')
    if set(chosen) - available:
        raise ValueError(f'Unknown tasks: {sorted(set(chosen)-available)}')
    return chosen

def load_tasks(path):
    value = json.loads(Path(path).read_text())
    if isinstance(value, dict):
        value = value['tasks']
    if not isinstance(value, list):
        raise ValueError('Task file must be a JSON list or an object containing tasks')
    return value
