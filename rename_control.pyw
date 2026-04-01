from __future__ import annotations

from rename_core import DEFAULT_CONFIG_PATH
from rename_tool import ControlPanel


if __name__ == "__main__":
    ControlPanel(DEFAULT_CONFIG_PATH).run()
