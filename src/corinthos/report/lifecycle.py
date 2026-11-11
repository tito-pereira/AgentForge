# SPDX-License-Identifier: MPL-2.0
"""Project-bounded lifecycle projections, reconstructed from immutable post-state events."""

import json
from datetime import datetime

from corinthos.contracts import IntegrityError
from corinthos.lifecycle.repository import digest


def project(rows, cutoff):
    records, state = {}, None
    origins = {row["record_id"]: row for row in rows["lc_records"]}
    events = []
    for row in rows["lc_events"]:
        if datetime.fromisoformat(row["occurred_at"]) > datetime.fromisoformat(cutoff):
            continue
        event = {**row, "data": json.loads(row["data"])}
        events.append(event)
        post = event["data"].get("record")
        if post is not None:
            source = origins.get(post["record_id"])
            if source is None:
                raise IntegrityError("A lifecycle event lost its immutable origin.")
            origin = json.loads(source["origin"])
            if (
                digest(origin) != source["origin_sha256"]
                or post["origin_sha256"] != source["origin_sha256"]
                or digest(post["snapshot"]) != post["snapshot_sha256"]
            ):
                raise IntegrityError(
                    "A lifecycle historical projection failed its integrity check."
                )
            records[post["record_id"]] = {**post, "origin": origin}
        if "project" in event["data"]:
            state = event["data"]["project"]
    return {"records": list(records.values()), "project": state, "events": events}


def delivery(snapshot):
    matching = [
        record
        for record in snapshot["lifecycle"]["records"]
        if record["kind"] == "VERSION"
        and record["state"] == "DELIVERED"
        and record["origin"]["artifact_identity"] == snapshot["artifact_identity"]
        and record["origin"]["project_ref"]
        == {
            key: snapshot["project"]["metadata"][key]
            for key in ("contract_id", "revision_id", "contract_type", "project_id")
        }
    ]
    if not matching:
        return None
    version = matching[-1]
    previous = next(
        (
            record
            for record in snapshot["lifecycle"]["records"]
            if record["record_id"] == version["origin"]["previous_version_id"]
        ),
        None,
    )
    return {
        "product_version": version["origin"]["product_version"],
        "previous_version": previous["origin"]["product_version"] if previous else None,
        "delivery": "DELIVERED",
        "availability": False,
        "provenance": {
            "version_id": version["record_id"],
            "origin_sha256": version["origin_sha256"],
        },
        "gaps": [
            "Delivery records retained packages; current launcher availability is unobserved."
        ],
    }


def summary(snapshot):
    lifecycle = snapshot.get("lifecycle", {})
    records = lifecycle.get("records", [])
    notes, feedback = [], []
    state = lifecycle.get("project")
    if state is not None:
        notes.append(
            f"Playtest tracker {state['tracker_id']}; enabled={state['enabled']}; "
            f"active build={state['active_build_id']}; pending build={state['pending_build_id']}."
        )
    for record in records:
        origin = record["origin"]
        notes.append(
            f"Lifecycle {record['kind']} {record['record_id']} at version {record['version']}: "
            f"{record['state']}; immutable origin sha256 {record['origin_sha256']}."
        )
        if record["kind"] == "FEEDBACK":
            admission = origin["admission"]
            feedback.append(
                {
                    "feedback_id": record["record_id"],
                    "build_id": origin["build_id"],
                    "milestone_id": admission["milestone_id"],
                    "status": f"{record['state']}; observer={origin['observer']}; "
                    f"route={record['snapshot'].get('route', 'UNTRIAGED')}",
                }
            )
            notes.append(
                f"Feedback {record['record_id']} originated in tracker {origin['tracker_id']}, "
                f"session {origin['session_id']}; observation: {origin['body']}"
            )
        elif record["kind"] == "EVOLUTION":
            notes.append(
                f"Evolution from version {origin['version_id']}, authority class "
                f"{origin['change_class']}: {origin['reason']}"
            )
        elif record["kind"] == "VERSION":
            notes.append(
                f"Delivered version {origin['product_version']} from {origin['previous_version_id']}; "
                "delivery and human acceptance remain separate."
            )
        elif record["kind"] == "BUILD":
            readiness = record["snapshot"].get("readiness") or {}
            notes.append(
                f"Build {record['record_id']} covers cumulative milestones "
                f"{origin['milestone_ids']} and checkpoints {origin['checkpoint_ids']} under "
                f"Workflow {origin['workflow_ref']['revision_id']}; recorded Workflow readiness "
                f"{readiness.get('state', 'NOT_VERIFIED')}. Readiness is separate from independent "
                "Validation; Report does not rerun its procedures or establish admission."
            )
        elif record["kind"] == "SESSION":
            notes.append(
                f"Session {record['record_id']} retains build {origin['build_id']}, milestone "
                f"{origin['admission']['milestone_id']}, predecessor {origin['predecessor_id']}; "
                f"current recorded state {record['state']}."
            )
    return notes, feedback
