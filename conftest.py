from __future__ import annotations

import sys
from pathlib import Path


agent_root = Path(__file__).resolve().parent
if str(agent_root) not in sys.path:
    sys.path.insert(0, str(agent_root))
