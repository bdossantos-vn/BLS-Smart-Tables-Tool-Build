"""Template import/export helpers.

Templates store configuration only and never include respondent-level data.
"""

from __future__ import annotations

import json
from typing import Any


def parse_template_bytes(raw_bytes: bytes) -> dict[str, Any]:
    """Parse uploaded template bytes into a configuration dictionary."""
    return json.loads(raw_bytes.decode("utf-8"))

