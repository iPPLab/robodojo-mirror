from robodojo_mirror import MirrorConfig, attach, configure_launcher


def before_app_launcher(args):

    return configure_launcher(args)


def create_mirror_environment(env_cfg, simulation_app, condition='single_mirror', state_only=False):
    from src.eval_client.eval_env import create_eval_env
    env=create_eval_env(env_cfg,simulation_app)
    return attach(env,MirrorConfig(condition=condition,capture_rgb=not state_only))
