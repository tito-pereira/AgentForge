# SPDX-License-Identifier: MPL-2.0
"""Exercise the public kernel API with synthetic data in a temporary workspace."""

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from corinthos.contracts import (
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
    validate_schema,
)

EXAMPLES = Path(__file__).with_name("contracts")
ORDER = (
    "project",
    "technology-decision",
    "module",
    "workflow",
    "validation",
    "validation-result",
    "evidence-report",
    "project-revision-request",
)


def main() -> None:
    documents = [json.loads((EXAMPLES / f"{name}.json").read_text("utf-8")) for name in ORDER]
    for document in documents:
        validate_schema(document)
    first = ContractRef.from_document(documents[0])
    second = deepcopy(documents[0])
    second["metadata"].update(
        revision_id="demo-intent-r2",
        version=2,
        supersedes=first.to_json(),
        approval={"kind": "HUMAN", "approval_id": "example-approval-r2", "actor_id": "demo-owner"},
    )
    second["payload"]["scope"]["included"].append("Document the local invocation")

    # Fixed synthetic receipts exercise the verifier API without a real approval service.
    receipts = frozenset(
        approval_request(document)
        for document in [*documents, second]
        if document["metadata"]["approval"] is not None
    )

    def context_for(document: dict) -> PublishContext:
        origin = document["metadata"]["provenance"]
        return PublishContext(origin["engine"], origin["actor_id"], receipts.__contains__)

    with TemporaryDirectory(prefix="corinthos-contract-demo-") as directory:
        store = ContractStore(directory)
        references = [
            store.publish(document, context=context_for(document)) for document in documents
        ]
        store.publish(second, context=context_for(second))
        reopened = ContractStore(directory)
        assert reopened.get(first) == documents[0]
        assert reopened.resolve_active(first.contract_id) == second
        assert reopened.get(references[3])["payload"]["project_contract_ref"] == first.to_json()
        assert reopened.list_revisions(first.contract_id) == [documents[0], second]
        events = reopened.list_events()

        invalid = deepcopy(documents[-1])
        invalid["metadata"].update(
            contract_id="demo-invalid-request", revision_id="demo-invalid-r1"
        )
        invalid["payload"]["request_id"] = "demo-invalid-base"
        invalid["payload"]["base_contract_version"]["revision_id"] = "missing-revision"
        try:
            reopened.publish(invalid, context=context_for(invalid))
        except IntegrityError:
            assert reopened.list_events() == events
            assert reopened.get(ContractRef.from_document(invalid)) is None
        else:
            raise AssertionError("The store accepted a missing base revision.")

    print(f"Published {len(references)} contract types and reopened {len(events)} revisions.")
    print("Resolved the historical project revision and rejected an invalid publication.")


if __name__ == "__main__":
    main()
