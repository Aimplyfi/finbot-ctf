"""FinMail address routing -- resolves email addresses to inbox deliveries.

Used by both the FinMail MCP server (agent-driven) and portal API endpoints
(user-driven compose). The inbox_type is always determined by this application
logic, never by LLMs or agents.
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from finbot.core.data.models import User, Vendor
from finbot.mcp.servers.finmail.repositories import EmailRepository

logger = logging.getLogger(__name__)


def get_admin_address(namespace: str) -> str:
    """Derive the canonical admin address from a namespace."""
    return f"admin@{namespace}.finbot"


def _is_admin_address(email_addr: str, namespace: str) -> bool:
    return email_addr == get_admin_address(namespace)


def route_and_deliver(
    db: Session,
    repo: EmailRepository,
    namespace: str,
    to: list[str],
    subject: str,
    body: str,
    message_type: str = "general",
    sender_name: str = "CineFlow Productions - FinBot",
    sender_type: str = "agent",
    from_address: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    related_invoice_id: int | None = None,
) -> dict[str, Any]:
    """Resolve addresses and create Email rows in the correct inboxes.

    Returns a delivery summary with the list of deliveries and counts.
    """
    to_json = json.dumps(to) if to else None
    cc_json = json.dumps(cc) if cc else None
    bcc_json = json.dumps(bcc) if bcc else None

    deliveries: list[dict] = []

    for role, addresses in [("to", to), ("cc", cc), ("bcc", bcc)]:
        for email_addr in (addresses or []):
            visible_bcc = bcc_json if role == "bcc" else None

            vendor = (
                db.query(Vendor)
                .filter(Vendor.namespace == namespace, Vendor.email == email_addr)
                .first()
            )
            if vendor:
                repo.create_email(
                    inbox_type="vendor",
                    vendor_id=vendor.id,
                    subject=subject,
                    body=body,
                    message_type=message_type,
                    sender_name=sender_name,
                    sender_type=sender_type,
                    from_address=from_address,
                    channel="email",
                    related_invoice_id=related_invoice_id,
                    to_addresses=to_json,
                    cc_addresses=cc_json,
                    bcc_addresses=visible_bcc,
                    recipient_role=role,
                )
                deliveries.append({"type": "vendor", "vendor_id": vendor.id, "email": email_addr, "role": role})
                continue

            if _is_admin_address(email_addr, namespace):
                repo.create_email(
                    inbox_type="admin",
                    subject=subject,
                    body=body,
                    message_type=message_type,
                    sender_name=sender_name,
                    sender_type=sender_type,
                    from_address=from_address,
                    channel="email",
                    related_invoice_id=related_invoice_id,
                    to_addresses=to_json,
                    cc_addresses=cc_json,
                    bcc_addresses=visible_bcc,
                    recipient_role=role,
                )
                deliveries.append({"type": "admin", "email": email_addr, "role": role})
                continue

            user = (
                db.query(User)
                .filter(User.namespace == namespace, User.email == email_addr)
                .first()
            )
            if user:
                repo.create_email(
                    inbox_type="admin",
                    subject=subject,
                    body=body,
                    message_type=message_type,
                    sender_name=sender_name,
                    sender_type=sender_type,
                    from_address=from_address,
                    channel="email",
                    related_invoice_id=related_invoice_id,
                    to_addresses=to_json,
                    cc_addresses=cc_json,
                    bcc_addresses=visible_bcc,
                    recipient_role=role,
                )
                deliveries.append({"type": "admin", "email": email_addr, "role": role})
                continue

            logger.warning("Unresolvable address: %s in namespace %s", email_addr, namespace)
            deliveries.append({"type": "undeliverable", "email": email_addr, "role": role})

    return {
        "sent": True,
        "subject": subject,
        "deliveries": deliveries,
        "delivery_count": len([d for d in deliveries if d["type"] != "undeliverable"]),
    }
