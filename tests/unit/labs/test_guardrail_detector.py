"""Tests for GuardrailPreventionDetector."""

import pytest

from finbot.ctf.detectors.implementations.guardrail_prevention import (
    GuardrailPreventionDetector,
)
from finbot.ctf.detectors.registry import create_detector


class TestGuardrailPreventionDetector:
    """Detector logic for labs guardrail prevention challenges."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.detector = GuardrailPreventionDetector(
            challenge_id="test-guardrail",
            config={"required_hook_kind": "before_tool"},
        )

    def test_registry_lookup(self):
        d = create_detector("GuardrailPreventionDetector", "test", {})
        assert d is not None
        assert isinstance(d, GuardrailPreventionDetector)

    def test_relevant_event_types(self):
        types = self.detector.get_relevant_event_types()
        assert "agent.guardrail.*" in types

    def test_matches_guardrail_events(self):
        assert self.detector.matches_event_type("agent.guardrail.webhook_completed")
        assert self.detector.matches_event_type("agent.guardrail.webhook_timeout")
        assert not self.detector.matches_event_type("agent.invoice_agent.tool_call_start")

    @pytest.mark.asyncio
    async def test_block_verdict_detected(self, db):
        event = {
            "event_type": "agent.guardrail.webhook_completed",
            "hook_kind": "before_tool",
            "outcome": "completed",
            "verdict": "block",
            "reason": "suspicious tool call",
            "tool_name": "approve_invoice",
            "latency_ms": 120,
        }
        result = await self.detector.check_event(event, db)
        assert result.detected is True
        assert result.confidence == 1.0
        assert result.evidence["verdict"] == "block"
        assert result.evidence["tool_name"] == "approve_invoice"

    @pytest.mark.asyncio
    async def test_allow_verdict_not_detected(self, db):
        event = {
            "event_type": "agent.guardrail.webhook_completed",
            "hook_kind": "before_tool",
            "outcome": "completed",
            "verdict": "allow",
        }
        result = await self.detector.check_event(event, db)
        assert result.detected is False

    @pytest.mark.asyncio
    async def test_timeout_not_detected(self, db):
        event = {
            "event_type": "agent.guardrail.webhook_timeout",
            "hook_kind": "before_tool",
            "outcome": "timeout",
            "verdict": None,
        }
        result = await self.detector.check_event(event, db)
        assert result.detected is False
        assert "timeout" in result.evidence.get("outcome", "")

    @pytest.mark.asyncio
    async def test_wrong_hook_kind_ignored(self, db):
        event = {
            "event_type": "agent.guardrail.webhook_completed",
            "hook_kind": "after_model",
            "outcome": "completed",
            "verdict": "block",
        }
        result = await self.detector.check_event(event, db)
        assert result.detected is False

    @pytest.mark.asyncio
    async def test_required_tool_name_filter(self, db):
        detector = GuardrailPreventionDetector(
            challenge_id="test",
            config={
                "required_hook_kind": "before_tool",
                "required_tool_name": "approve_invoice",
            },
        )
        matching = {
            "event_type": "agent.guardrail.webhook_completed",
            "hook_kind": "before_tool",
            "outcome": "completed",
            "verdict": "block",
            "tool_name": "approve_invoice",
        }
        wrong_tool = {**matching, "tool_name": "get_vendor_details"}

        assert (await detector.check_event(matching, db)).detected is True
        assert (await detector.check_event(wrong_tool, db)).detected is False

    @pytest.mark.asyncio
    async def test_non_guardrail_event_ignored(self, db):
        event = {
            "event_type": "business.invoice.decision",
            "hook_kind": "before_tool",
        }
        result = await self.detector.check_event(event, db)
        assert result.detected is False

    def test_invalid_hook_kind_config(self):
        with pytest.raises(ValueError, match="required_hook_kind"):
            GuardrailPreventionDetector(
                challenge_id="test",
                config={"required_hook_kind": "invalid_kind"},
            )
