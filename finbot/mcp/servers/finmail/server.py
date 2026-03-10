"""FinMail MCP Server -- internal email system for vendor and admin communications.

Agents use this to send and read messages. Messages are stored in the unified
emails table -- no real emails are sent.

The tool descriptions here are the CTF attack surface for email-based scenarios:
admins can override them via tool_overrides_json to introduce email attack patterns.
"""

import logging
from typing import Any

from fastmcp import FastMCP

from finbot.core.auth.session import SessionContext
from finbot.core.data.database import get_db
from finbot.mcp.servers.finmail.repositories import EmailRepository
from finbot.mcp.servers.finmail.routing import get_admin_address, route_and_deliver

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "max_results_per_query": 50,
    "default_sender": "CineFlow Productions - FinBot",
}


def create_finmail_server(
    session_context: SessionContext,
    server_config: dict[str, Any] | None = None,
) -> FastMCP:
    """Create a namespace-scoped FinMail MCP server instance."""
    config = {**DEFAULT_CONFIG, **(server_config or {})}
    mcp = FastMCP("FinMail")

    @mcp.tool
    def send_email(
        to: list[str],
        subject: str,
        body: str,
        message_type: str = "general",
        sender_name: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        related_invoice_id: int = 0,
    ) -> dict[str, Any]:
        """Send an email message. Routes to the correct inbox based on recipient addresses.

        Addresses are resolved within the current namespace:
        - Vendor email addresses deliver to the vendor's inbox
        - The admin address (admin@<namespace>.finbot) delivers to the admin inbox
        - The user's real email also delivers to the admin inbox

        Args:
            to: List of To: recipient email addresses
            subject: Email subject line
            body: Email message body
            message_type: One of: status_update, payment_update, compliance_alert, action_required, payment_confirmation, reminder, general
            sender_name: Name of the sender (defaults to platform name)
            cc: Optional CC: recipient email addresses
            bcc: Optional BCC: recipient email addresses (hidden from other recipients)
            related_invoice_id: Optional invoice ID this email relates to (0 for none)
        """
        effective_sender = sender_name or config.get("default_sender", "CineFlow Productions - FinBot")
        inv_id = related_invoice_id if related_invoice_id > 0 else None

        db = next(get_db())
        repo = EmailRepository(db, session_context)

        return route_and_deliver(
            db=db,
            repo=repo,
            namespace=session_context.namespace,
            to=to,
            subject=subject,
            body=body,
            message_type=message_type,
            sender_name=effective_sender,
            sender_type="agent",
            from_address=get_admin_address(session_context.namespace),
            cc=cc,
            bcc=bcc,
            related_invoice_id=inv_id,
        )

    @mcp.tool
    def list_inbox(
        inbox: str = "admin",
        vendor_id: int = 0,
        message_type: str = "",
        unread_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List messages in an inbox.

        Args:
            inbox: Which inbox to list: "vendor" or "admin"
            vendor_id: Required when inbox is "vendor" -- the vendor ID whose inbox to read
            message_type: Optional filter by type (e.g., "payment_update", "compliance_alert")
            unread_only: If true, only return unread messages
            limit: Maximum number of messages to return
        """
        db = next(get_db())
        repo = EmailRepository(db, session_context)
        max_limit = config.get("max_results_per_query", 50)
        effective_limit = min(limit, max_limit)
        is_read_filter = False if unread_only else None
        type_filter = message_type if message_type else None

        if inbox == "vendor":
            if vendor_id <= 0:
                return {"error": "vendor_id is required when inbox is 'vendor'"}
            messages = repo.list_vendor_emails(
                vendor_id=vendor_id,
                message_type=type_filter,
                is_read=is_read_filter,
                limit=effective_limit,
            )
            return {
                "inbox": "vendor",
                "vendor_id": vendor_id,
                "messages": [m.to_dict() for m in messages],
                "count": len(messages),
            }

        messages = repo.list_admin_emails(
            message_type=type_filter,
            is_read=is_read_filter,
            limit=effective_limit,
        )
        return {
            "inbox": "admin",
            "messages": [m.to_dict() for m in messages],
            "count": len(messages),
        }

    @mcp.tool
    def read_email(
        message_id: int,
    ) -> dict[str, Any]:
        """Read a specific email message by ID.

        Args:
            message_id: The ID of the message to read
        """
        db = next(get_db())
        repo = EmailRepository(db, session_context)
        msg = repo.get_email(message_id)
        if not msg:
            return {"error": f"Message {message_id} not found"}
        return {"message": msg.to_dict()}

    @mcp.tool
    def search_emails(
        query: str,
        inbox: str = "admin",
        vendor_id: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search emails by subject or body text.

        Args:
            query: Search term to look for in subject and body
            inbox: Which inbox to search: "vendor" or "admin"
            vendor_id: Required when inbox is "vendor"
            limit: Maximum results to return
        """
        db = next(get_db())
        repo = EmailRepository(db, session_context)
        max_limit = config.get("max_results_per_query", 50)
        effective_limit = min(limit, max_limit)

        if inbox == "vendor":
            if vendor_id <= 0:
                return {"error": "vendor_id is required when inbox is 'vendor'"}
            messages = repo.list_vendor_emails(vendor_id=vendor_id, limit=effective_limit * 3)
        else:
            messages = repo.list_admin_emails(limit=effective_limit * 3)

        query_lower = query.lower()
        results = [
            m for m in messages
            if query_lower in (m.subject or "").lower() or query_lower in (m.body or "").lower()
        ][:effective_limit]

        return {
            "query": query,
            "inbox": inbox,
            "results": [m.to_dict() for m in results],
            "count": len(results),
        }

    @mcp.tool
    def mark_as_read(
        message_id: int,
    ) -> dict[str, Any]:
        """Mark an email message as read.

        Args:
            message_id: The ID of the message to mark as read
        """
        db = next(get_db())
        repo = EmailRepository(db, session_context)
        msg = repo.mark_as_read(message_id)
        if not msg:
            return {"error": f"Message {message_id} not found"}
        return {"marked_read": True, "message_id": message_id}

    return mcp
