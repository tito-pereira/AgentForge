# SPDX-License-Identifier: MPL-2.0
"""Keep planning state separate while reusing the shared CAS and turn mechanics."""

from ..project_manager.repository import SessionRepository


class WorkflowRepository(SessionRepository):
    """Persist Workflow planning in its own operational namespace."""

    _sessions_table = "wf_sessions"
    _turns_table = "wf_turns"
