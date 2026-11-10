# SPDX-License-Identifier: MPL-2.0
"""Explicit external-agent adapters with shared mandatory policy."""

from .model import AgentResult, Capabilities, ContextInput, PreparedContext
from .service import AdapterManager

__all__ = ["AdapterManager", "AgentResult", "Capabilities", "ContextInput", "PreparedContext"]
