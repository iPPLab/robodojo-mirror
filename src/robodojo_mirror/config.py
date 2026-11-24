from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

CONDITIONS = ("no_mirror", "single_mirror", "dual_mirror", "mirror_tabletop")
CONTROLS = ("single_panel", "dual_panel")
ALIASES = {"double_mirror": "dual_mirror", "table_mirror": "mirror_tabletop"}
REVISION = "independent_normal_5cm_v1"

@dataclass(frozen=True)
class MirrorConfig:
    condition: str = "no_mirror"
    clearance_m: float = .05

    height_m: float | None = None
    thickness_m: float = .004
    mirror_spp: int = 128
    capture_pass_limit: int = 32


    capture_rgb: bool = True
    record_contacts: bool = True

    def __post_init__(self):
        object.__setattr__(self, "condition", ALIASES.get(self.condition, self.condition))
        if self.condition not in CONDITIONS + CONTROLS:
            raise ValueError(f"Unknown scene condition: {self.condition}")
        if self.height_m is None:
            object.__setattr__(self, "height_m",
                               .8 if self.condition in ('dual_mirror', 'dual_panel') else 1.3)
        for name in ("clearance_m", "height_m", "thickness_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("mirror_spp", "capture_pass_limit"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("capture_rgb", "record_contacts"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")

    @property
    def revision(self):
        if self.condition in ('single_mirror', 'single_panel'):
            return ('single_normal_5cm_table_edge_v1' if self.clearance_m == .05
                    else 'single_custom_offset_table_edge_v1')
        return REVISION if self.clearance_m == .05 else "custom_normal_offset_v1"
