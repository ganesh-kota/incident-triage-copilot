"""
Triage Agent — the core reasoning loop.

Flow:
  1. Receive incident input from user
  2. Connect to MCP servers → discover tools
  3. Reasoning loop (LLM + tool calls)
  4. Apply context policy on each tool result
  5. Produce final triage output
  6. Run evaluation hooks
  7. Optionally create a ticket

Supports two modes:
  - REAL: uses OpenAI-compatible LLM with function calling
  - MOCK: demonstrates the full flow with pre-scripted responses
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

from openai import AsyncAzureOpenAI, AsyncOpenAI

from ..mcp_client.client import MCPClient
from .context_policy import redact_secrets, summarize_tool_result
from .evaluator import format_eval_report, run_all_evals
from .prompts import MOCK_TRIAGE_RESPONSE, TRIAGE_SYSTEM_PROMPT
from .state import StateManager, ToolCall

logger = logging.getLogger("triage_agent")


class TriageAgent:
    """
    The Incident Triage Copilot agent.

    Connects to MCP tool servers, reasons over evidence,
    and produces a grounded triage report.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        mock_mode: bool = False,
        enable_eval: bool = True,
        *,
        llm_provider: str = "openai",
        azure_endpoint: str = "",
        azure_deployment: str = "",
        azure_api_version: str = "2024-08-01-preview",
    ):
        self.mock_mode = mock_mode
        self.enable_eval = enable_eval
        self.model = model
        self.state = StateManager()
        self.mcp_client = MCPClient()

        if not mock_mode and api_key:
            if llm_provider == "azure_openai" and azure_endpoint:
                self.model = azure_deployment  # use deployment name as model
                self.llm = AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=azure_endpoint,
                    azure_deployment=azure_deployment,
                    api_version=azure_api_version,
                )
                logger.info(
                    f"Using Azure OpenAI — endpoint={azure_endpoint}, "
                    f"deployment={azure_deployment}, api_version={azure_api_version}"
                )
            else:
                self.llm = AsyncOpenAI(api_key=api_key, base_url=base_url)
                logger.info(f"Using OpenAI — model={model}")
        else:
            self.llm = None

    async def initialize(self) -> dict:
        """
        Connect to all MCP servers and discover available tools.
        Returns a summary of connected servers and tools.
        """
        logger.info("Initializing MCP connections...")
        tools = await self.mcp_client.connect()

        summary = {}
        for tool in tools:
            server = tool.server_name
            if server not in summary:
                summary[server] = []
            summary[server].append(tool.name)

        logger.info(f"Connected to {len(summary)} servers, {len(tools)} tools available")
        return summary

    async def triage(self, alert_text: str, **kwargs) -> dict:
        """
        Run a full triage on an incident.

        Args:
            alert_text: The raw alert/pager text.
            **kwargs: Optional fields — service_name, environment,
                      time_range_minutes, severity, stack_trace,
                      additional_context.

        Returns:
            dict with keys: triage_output, eval_report, ticket (if created),
            tool_calls_made, incident_id.
        """
        # Generate incident ID
        incident_id = f"INC-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Initialize task state
        self.state.reset()
        self.state.task.incident_id = incident_id
        self.state.task.service_name = kwargs.get("service_name")
        self.state.task.environment = kwargs.get("environment", "production")
        self.state.task.severity = kwargs.get("severity")
        self.state.task.time_range_minutes = kwargs.get("time_range_minutes", 15)

        # Build the initial user message
        user_msg = self._build_user_message(alert_text, **kwargs)
        self.state.add_user_message(user_msg)

        if self.mock_mode:
            return await self._mock_triage(incident_id, alert_text, **kwargs)
        else:
            return await self._real_triage(incident_id)

    def _build_user_message(self, alert_text: str, **kwargs) -> str:
        """Construct the initial user message from incident input."""
        parts = [f"**Alert:**\n{alert_text}"]

        if kwargs.get("service_name"):
            parts.append(f"**Service:** {kwargs['service_name']}")
        if kwargs.get("environment"):
            parts.append(f"**Environment:** {kwargs['environment']}")
        if kwargs.get("severity"):
            parts.append(f"**Severity:** {kwargs['severity']}")
        if kwargs.get("time_range_minutes"):
            parts.append(f"**Time Range:** last {kwargs['time_range_minutes']} minutes")
        if kwargs.get("stack_trace"):
            parts.append(f"**Stack Trace:**\n```\n{kwargs['stack_trace']}\n```")
        if kwargs.get("additional_context"):
            parts.append(f"**Additional Context:** {kwargs['additional_context']}")

        return "\n\n".join(parts)

    async def _real_triage(self, incident_id: str) -> dict:
        """Run triage with a real LLM using tool calling."""
        if not self.llm:
            raise RuntimeError("No LLM configured. Set OPENAI_API_KEY or use --mock mode.")

        tools = self.mcp_client.get_openai_tools()
        messages = self.state.get_conversation_for_llm(TRIAGE_SYSTEM_PROMPT)
        tool_calls_made: list[str] = []

        # Reasoning loop — up to 10 iterations of tool calling
        max_iterations = 10
        for iteration in range(max_iterations):
            logger.info(f"LLM iteration {iteration + 1}/{max_iterations}")

            # Build request kwargs — some models (e.g. gpt-5-nano) don't support temperature
            create_kwargs: dict = dict(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
            )
            # Only set temperature for models that support it
            if not isinstance(self.llm, AsyncAzureOpenAI):
                create_kwargs["temperature"] = 0.1

            response = await self.llm.chat.completions.create(**create_kwargs)

            choice = response.choices[0]

            # If no tool calls, this is the final answer
            if choice.finish_reason == "stop" or not choice.message.tool_calls:
                final_output = choice.message.content or ""
                self.state.add_assistant_message(final_output)
                break

            # Process tool calls
            messages.append(choice.message.model_dump())

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                logger.info(f"Tool call: {func_name}({json.dumps(func_args)[:100]})")

                # Execute via MCP client
                start_time = time.time()
                result = await self.mcp_client.call_tool(func_name, func_args)
                latency = (time.time() - start_time) * 1000

                # Apply context policy
                clean_result = summarize_tool_result(result)

                # Record in state
                tc = ToolCall(
                    tool_name=func_name,
                    arguments=func_args,
                    result=clean_result,
                    latency_ms=latency,
                )
                self.state.add_tool_result(tc)
                tool_calls_made.append(func_name)

                # Feed result back to LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": clean_result,
                })
        else:
            final_output = "⚠️ Max tool-calling iterations reached. Partial triage below:\n\n"
            final_output += self.state.get_tool_results_summary()

        # Run evaluation hooks
        eval_report = ""
        if self.enable_eval:
            evals = run_all_evals(final_output, tool_calls_made, self.state.task.severity)
            eval_report = format_eval_report(evals)

        return {
            "incident_id": incident_id,
            "triage_output": final_output,
            "eval_report": eval_report,
            "tool_calls_made": tool_calls_made,
            "tool_call_count": len(tool_calls_made),
        }

    async def _mock_triage(self, incident_id: str, alert_text: str, **kwargs) -> dict:
        """
        Demonstrate the full triage flow without a real LLM.
        Calls real MCP servers but uses pre-scripted final output.
        """
        tool_calls_made: list[str] = []
        service = kwargs.get("service_name", "payment-service")

        # Simulate the evidence-gathering phase with real MCP tool calls
        mock_calls = [
            ("logs_server__query_logs", {"service": service, "level": "ERROR"}),
            ("logs_server__extract_error_signatures", {"service": service}),
            ("metrics_server__query_metrics", {"service": service, "metric_name": "error_rate"}),
            ("metrics_server__get_active_alerts", {"service": service}),
            ("metrics_server__get_deployments", {"service": service}),
            ("runbook_server__search_runbooks", {"query": "connection refused database"}),
        ]

        for tool_name, args in mock_calls:
            start = time.time()
            try:
                result = await self.mcp_client.call_tool(tool_name, args)
                latency = (time.time() - start) * 1000
                clean = summarize_tool_result(result)
                tc = ToolCall(
                    tool_name=tool_name,
                    arguments=args,
                    result=clean,
                    latency_ms=latency,
                )
                self.state.add_tool_result(tc)
                tool_calls_made.append(tool_name)
                logger.info(f"✓ {tool_name} ({latency:.0f}ms)")
            except Exception as e:
                logger.warning(f"✗ {tool_name}: {e}")

        # Use pre-scripted triage output
        final_output = MOCK_TRIAGE_RESPONSE
        self.state.add_assistant_message(final_output)

        # Run evaluation hooks (even in mock mode — proves the eval system works)
        eval_report = ""
        if self.enable_eval:
            evals = run_all_evals(final_output, tool_calls_made, kwargs.get("severity"))
            eval_report = format_eval_report(evals)

        return {
            "incident_id": incident_id,
            "triage_output": final_output,
            "eval_report": eval_report,
            "tool_calls_made": tool_calls_made,
            "tool_call_count": len(tool_calls_made),
        }

    async def create_ticket(self, triage_result: dict) -> str | None:
        """Optionally create an incident ticket from triage results."""
        try:
            result = await self.mcp_client.call_tool(
                "ticketing_server__create_incident",
                {
                    "title": f"Incident {triage_result['incident_id']}",
                    "severity": self.state.task.severity or "SEV2",
                    "summary": triage_result["triage_output"][:500],
                    "service": self.state.task.service_name or "unknown",
                },
            )
            return result
        except Exception as e:
            logger.error(f"Failed to create ticket: {e}")
            return None

    async def shutdown(self):
        """Clean up all MCP connections."""
        await self.mcp_client.disconnect()
