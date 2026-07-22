from pathlib import Path

from contact_verifier.api.schemas import ContactOut
from contact_verifier.db.models import EmailStatus
from contact_verifier.mcp import server

ROOT = Path(__file__).resolve().parents[1]


def test_readme_tracks_verification_status_lifecycle() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Stored contacts begin as `unknown`, which means not yet assessed." in readme
    terminal = {EmailStatus.VALID, EmailStatus.INVALID, EmailStatus.RISKY}
    assert {status.value for status in terminal} == {"valid", "invalid", "risky"}
    for status in ("`valid`", "`invalid`", "`risky`", "`unknown`"):
        assert status in readme


def test_public_interfaces_scope_status_and_score_to_rule_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "not calibrated probabilities" in readme
    assert "not mailbox validity" in (ContactOut.model_fields["status"].description or "")
    assert "not mailbox-existence or delivery probability" in (
        ContactOut.model_fields["heuristic_score"].description or ""
    )
    mcp_doc = " ".join((server.search_contacts.__doc__ or "").split())
    assert "not mailbox-validity claims" in mcp_doc
    assert "cannot establish mailbox existence" in architecture


def test_public_docs_name_routing_evidence_instead_of_deliverability() -> None:
    docs = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "ARCHITECTURE.md")
    )

    assert "DNS/MX deliverability" not in docs
    assert "mail-routing evidence" in docs


def test_mcp_auth_explanation_is_scoped_to_the_stdio_transport() -> None:
    module_doc = server.__doc__ or ""

    assert "this stdio transport does not carry the REST authentication header" in module_doc
    assert "MCP has no HTTP headers" not in module_doc
