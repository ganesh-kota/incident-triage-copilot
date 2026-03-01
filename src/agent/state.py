"""
State Management — conversation, task, and tool-results memory.

Three memory layers:
  1. Conversation memory — what the user said, what the agent replied
  2. Task memory — current incident context, what's been tried
  3. Tool-results memory — cached tool outputs (avoid re-querying)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool_name: str
    arguments: dict[str, Any]
    result: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    latency_ms: float = 0.0
    success: bool = True


@dataclass
class TaskState:
    """
    Current incident task context.
    Tracks what the agent knows and what it's tried.
    """
    incident_id: str = ""
    service_name: str | None = None
    environment: str = "production"
    severity: str | None = None
    time_range_minutes: int = 15
    # What the agent has determined so far
    hypotheses: list[str] = field(default_factory=list)
    evidence_collected: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    # Phase tracking
    phase: str = "intake"  # intake → evidence_gathering → analysis → output

    def to_context_string(self) -> str:
        """Serialize task state for injection into the prompt."""
        parts = [f"Incident: {self.incident_id}"]
        if self.service_name:
            parts.append(f"Service: {self.service_name}")
        parts.append(f"Environment: {self.environment}")
        if self.severity:
            parts.append(f"Severity: {self.severity}")
        parts.append(f"Phase: {self.phase}")
        if self.tools_called:
            parts.append(f"Tools already called: {', '.join(self.tools_called)}")
        if self.hypotheses:
            parts.append(f"Working hypotheses: {'; '.join(self.hypotheses)}")
        return "\n".join(parts)


@dataclass
class StateManager:
    """
    Manages all three memory layers for the triage agent.
    """
    # Layer 1: Conversation memory
    conversation_history: list[dict[str, str]] = field(default_factory=list)

    # Layer 2: Task memory
    task: TaskState = field(default_factory=TaskState)

    # Layer 3: Tool-results cache
    tool_results: list[ToolCall] = field(default_factory=list)

    def add_user_message(self, content: str):
        """Record a user message."""
        self.conversation_history.append({
            "role": "user",
            "content": content,
        })

    def add_assistant_message(self, content: str):
        """Record an assistant response."""
        self.conversation_history.append({
            "role": "assistant",
            "content": content,
        })

    def add_tool_result(self, tool_call: ToolCall):
        """Cache a tool result and update task state."""
        self.tool_results.append(tool_call)
        if tool_call.tool_name not in self.task.tools_called:
            self.task.tools_called.append(tool_call.tool_name)

    def get_cached_result(self, tool_name: str, arguments: dict) -> str | None:
        """Check if we already called this tool with these args."""
        args_json = json.dumps(arguments, sort_keys=True)
        for tc in self.tool_results:
            if tc.tool_name == tool_name and json.dumps(tc.arguments, sort_keys=True) == args_json:
                return tc.result
        return None

    def get_conversation_for_llm(self, system_prompt: str) -> list[dict]:
        """
        Build the message list for the LLM, including system prompt
        and conversation history.
        """
        messages = [{"role": "system", "content": system_prompt}]

        # Inject task context as a system-level note
        if self.task.incident_id:
            messages.append({
                "role": "system",
                "content": f"[TASK CONTEXT]\n{self.task.to_context_string()}",
            })

        messages.extend(self.conversation_history)
        return messages

    def get_tool_results_summary(self) -> str:
        """Summarize all tool results collected so far."""
        if not self.tool_results:
            return "No tools called yet."
        lines = []
        for tc in self.tool_results:
            status = "✓" if tc.success else "✗"
            # Truncate result preview
            preview = tc.result[:200] + "..." if len(tc.result) > 200 else tc.result
            lines.append(f"{status} {tc.tool_name}({json.dumps(tc.arguments)}) → {preview}")
        return "\n".join(lines)

    def reset(self):
        """Clear all state for a new incident."""
        self.conversation_history.clear()
        self.task = TaskState()
        self.tool_results.clear()
