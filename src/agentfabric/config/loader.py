from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .spec import ConfigSpec


def load_config(path: str | Path) -> ConfigSpec:
    p = Path(path)
    data: Any
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ConfigSpec.model_validate(data)
