# SPDX-License-Identifier: MPL-2.0
"""Run a small read-only native acceptance case in a disposable project."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from corinthos.application.sessions import SessionApplication, session_view
from corinthos.bootstrap import initialize
from corinthos.contracts import ContractError
from corinthos.providers import SUPPORTED_PROVIDERS
from corinthos.work import WorkService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=SUPPORTED_PROVIDERS)
    parser.add_argument("--executable", help="Absolute path to the real native executable.")
    parser.add_argument("--timeout", default=60, type=int)
    args = parser.parse_args()
    # Keep disposable evidence off the user's normal project tree.
    with TemporaryDirectory(prefix="corinthos-live-session-") as directory:
        root = Path(directory).resolve() / "project"
        initialize(root)
        subprocess.run(
            ["git", "init", "--quiet", str(root)], check=True, capture_output=True, timeout=10
        )
        marker = root / "marker.txt"
        marker.write_bytes(b"CORINTHOS_PHASE3_OK\n")
        work = WorkService(root)
        original = work.create(
            scope_level="TASK",
            objective="Return CORINTHOS_PHASE3_OK verbatim.",
            acceptance_criteria=["Return the marker without editing the project."],
        )
        app = SessionApplication()
        try:
            initial = app.start(
                root,
                original.work_item_id,
                args.provider,
                timeout_seconds=args.timeout,
                read_only=True,
                executable=args.executable,
            )
            session = app.supervisor.wait(root, initial["session_id"])
            observed = app.events(root, session.session_id)
        except (ContractError, OSError) as error:
            print(
                json.dumps(
                    {
                        "provider": args.provider,
                        "status": "NOT_VERIFIED",
                        "reason": type(error).__name__,
                    }
                )
            )
            return 1
        finally:
            closed = app.supervisor.close()
        events = observed["events"]
        while len(observed["events"]) == 10:
            observed = app.events(
                root, session.session_id, after_sequence=observed["next_after_sequence"]
            )
            events.extend(observed["events"])
        invariants = {
            "trusted_terminal": session.state == "SUCCEEDED",
            "normalized_output": any(
                event["kind"] == "OUTPUT"
                and "CORINTHOS_PHASE3_OK" in event["payload"].get("text", "")
                for event in events
            ),
            "work_item_unchanged": work.get(original.work_item_id) == original,
            "marker_unchanged": marker.read_bytes() == b"CORINTHOS_PHASE3_OK\n",
            "owned_process_reaped": closed
            and not session.cleanup_unconfirmed
            and session.state == "SUCCEEDED",
        }
        verified = all(invariants.values())
        facts = session_view(session)
        result = {
            "provider": args.provider,
            "status": "VERIFIED_WITH_REAL_PROVIDER" if verified else "NOT_VERIFIED",
            "session_state": session.state,
            "provider_version": facts["provider_version"],
            "model": facts["model"],
            "usage": {
                key: facts[key]
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cached_tokens",
                    "reported_cost",
                    "reported_cost_currency",
                    "duration_ms",
                )
            },
            "event_kinds": sorted({event["kind"] for event in events}),
            "reason": events[-1]["payload"].get("reason") if events else None,
            "checks": invariants,
        }
        print(json.dumps(result, indent=2))
        return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
