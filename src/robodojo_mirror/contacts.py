class ContactLedger:
    def __init__(self, names):
        self.active = set()
        self.events = dict.fromkeys(names, 0)
        self.steps = {name:set() for name in names}
        self.controls = {name:set() for name in names}
        self.physics_steps = 0
        self.total_events = 0

    def update(self, active, control_step):
        active = set(active)
        if active - self.events.keys():
            raise ValueError('Unknown contact surface')
        if active and not self.active:
            self.total_events += 1
        for name in active:
            if name not in self.active:
                self.events[name] += 1
            self.steps[name].add(self.physics_steps)
            self.controls[name].add(control_step)
        self.active = active
        self.physics_steps += 1

    def summary(self):
        return dict(physics_steps=self.physics_steps,
            surfaces={n:dict(collision_events=self.events[n],
                contact_physics_steps=len(self.steps[n]), contact_control_steps=len(self.controls[n])) for n in self.events},
            total=dict(collision_events=self.total_events,
                surface_collision_events=sum(self.events.values()),
                contact_physics_steps=len(set().union(*self.steps.values())),
                contact_control_steps=len(set().union(*self.controls.values()))))
