"""
Improvement #3: Stuck Detection (Loop Breaker)

Inspired by: OpenHands (openhands/controller/stuck.py)
Addresses: Weakness #3 — no loop detection

Integration:
    In Agent.__init__():
        self.stuck_detector = StuckDetector(max_repeats=3)

    In Agent.run() main loop, after tool execution:
        for tool_call in response.tool_calls:
            self.stuck_detector.record_tool_call(tool_call["name"], tool_call["arguments"])

        stuck_reason = self.stuck_detector.is_stuck()
        if stuck_reason:
            self._emit(Event(
                type=EventType.ERROR,
                timestamp=datetime.now(),
                data={"error": f"Agent stuck: {stuck_reason}", "stuck": True},
            ))
            # Option A: inject recovery prompt
            # Option B: break
            break
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StuckDetector:
    """Detects when the agent is stuck in a loop.

    Checks for:
    1. Repeated identical tool calls (same name + args)
    2. Repeated identical LLM responses
    3. Alternating error patterns (A-B-A-B)
    4. Consecutive error streaks
    """

    def __init__(self, max_repeats: int = 3, window_size: int = 10):
        """Initialize stuck detector.

        Args:
            max_repeats: Number of repetitions before declaring stuck.
            window_size: Sliding window size for tracking history.
        """
        self.max_repeats = max_repeats
        self.window_size = window_size
        self._action_hashes: List[str] = []
        self._response_hashes: List[str] = []
        self._error_count: int = 0
        self._consecutive_errors: int = 0

    def _hash(self, data: str) -> str:
        """Create a short hash for comparison."""
        return hashlib.md5(data.encode()).hexdigest()[:12]

    def record_tool_call(self, name: str, arguments: Dict[str, Any]) -> None:
        """Record a tool call for loop detection."""
        key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        self._action_hashes.append(self._hash(key))
        if len(self._action_hashes) > self.window_size:
            self._action_hashes.pop(0)

    def record_response(self, content: str) -> None:
        """Record an LLM response for repetition detection."""
        self._response_hashes.append(self._hash(content.strip()))
        if len(self._response_hashes) > self.window_size:
            self._response_hashes.pop(0)

    def record_error(self) -> None:
        """Record an error occurrence."""
        self._error_count += 1
        self._consecutive_errors += 1

    def record_success(self) -> None:
        """Record a successful action (resets consecutive error counter)."""
        self._consecutive_errors = 0

    def is_stuck(self) -> Optional[str]:
        """Check if the agent appears stuck.

        Returns:
            Description of the stuck pattern, or None if not stuck.
        """
        # Check repeated tool calls
        if len(self._action_hashes) >= self.max_repeats:
            tail = self._action_hashes[-self.max_repeats:]
            if len(set(tail)) == 1:
                return f"Repeated identical tool call {self.max_repeats} times"

        # Check repeated responses
        if len(self._response_hashes) >= self.max_repeats:
            tail = self._response_hashes[-self.max_repeats:]
            if len(set(tail)) == 1:
                return f"Repeated identical response {self.max_repeats} times"

        # Check alternating pattern (AB AB AB)
        if len(self._action_hashes) >= 4:
            last4 = self._action_hashes[-4:]
            if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
                return "Alternating action pattern detected"

        # Check consecutive errors
        if self._consecutive_errors >= self.max_repeats:
            return f"Consecutive errors: {self._consecutive_errors}"

        return None

    def reset(self) -> None:
        """Reset all tracking state."""
        self._action_hashes.clear()
        self._response_hashes.clear()
        self._error_count = 0
        self._consecutive_errors = 0
