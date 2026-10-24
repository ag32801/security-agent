"""Interactive Command-Line Gemini Security Agent.

Orchestrates the conversation between the user, Google Gemini (via google-genai SDK),
and local Model Context Protocol (MCP) tool servers.
"""

import asyncio
import json
import os
import sys
from typing import List
from google import genai
from google.genai import types

from agent.config import load_config, PROJECT_ROOT
from agent.mcp_client import MCPClientManager

SYSTEM_INSTRUCTION = """You are a friendly, highly competent Windows Security AI Assistant.
Your mission is to help the user monitor and understand the security posture of their laptop.

Guidelines:
1. Always base your security evaluations on live data retrieved via your available tools (such as check_firewall_status and check_defender_status).
2. When answering questions regarding firewall or antivirus status, invoke the relevant tools first before forming conclusions.
3. If all firewall profiles (Domain, Private, Public) are active and real-time antivirus protection is enabled with recent signatures, reassure the user.
4. If any protection is disabled or signatures appear outdated, clearly flag it with an actionable recommendation.
5. Provide concise, structured, and easy-to-read risk summaries using bullet points.
"""


class SecurityAgent:
    """Agent orchestrator managing Gemini LLM sessions and MCP tool invocations."""

    def __init__(self) -> None:
        self.config = load_config()

        if not self.config.gemini_api_key or self.config.gemini_api_key == "your_gemini_api_key_here":
            print("\n" + "=" * 65)
            print("[ERROR] GEMINI_API_KEY is not set or is using the placeholder!")
            print(f"Please open: {PROJECT_ROOT / '.env'}")
            print("and paste your Gemini API key from https://aistudio.google.com/app/apikey")
            print("=" * 65 + "\n")
            sys.exit(1)

        # Initialize the official Google GenAI client
        self.gemini_client = genai.Client(api_key=self.config.gemini_api_key)
        self.mcp_manager = MCPClientManager(self.config)
        self.conversation_history: List[types.Content] = []

    async def start(self) -> None:
        """Starts MCP servers, verifies tools, and enters the interactive CLI loop."""
        print("=" * 65)
        print("  Windows Laptop Security AI Agent (Gemini + MCP)")
        print("=" * 65)
        print("Connecting to local MCP security servers...")

        await self.mcp_manager.connect_all()

        tool_count = len(self.mcp_manager.tools)
        if tool_count == 0:
            print("[Warning] No tools discovered. Check servers.json and server configurations.")
        else:
            print(f"[Ready] Discovered {tool_count} security tool(s):")
            for t_name in self.mcp_manager.tools.keys():
                print(f"  • {t_name}")

        print(f"[Model] Using Google Gemini: {self.config.gemini_model}")
        print("Type 'exit' or 'quit' to close the agent.\n")

        # Prepare Gemini generation config with tools and system instruction
        gemini_tools = self.mcp_manager.get_gemini_tools()
        thinking_cfg = None
        try:
            level = self.config.gemini_thinking_level.upper()
            if level in ("MINIMAL", "OFF", "NONE", "0"):
                level = "LOW"
            thinking_cfg = types.ThinkingConfig(thinking_level=level)
        except Exception:
            thinking_cfg = None

        gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=gemini_tools if gemini_tools else None,
            temperature=0.2,  # Low temperature for factual, deterministic analysis
            thinking_config=thinking_cfg,
        )

        try:
            while True:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nSession interrupted.")
                    break

                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit", "q"):
                    print("Exiting Security Agent. Goodbye!")
                    break

                await self._process_turn(user_input, gen_config)

        finally:
            print("\nShutting down MCP servers...")
            await self.mcp_manager.close()
            print("All services stopped.")

    async def _process_turn(
        self, user_input: str, gen_config: types.GenerateContentConfig
    ) -> None:
        """Processes a single conversational turn, resolving any tool calls in a loop."""
        # Append user message to history
        self.conversation_history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_input)],
            )
        )

        first_step = True
        while True:
            # Show immediate progress indicator so the user is never left wondering
            if first_step:
                print("  [Contacting Gemini...]", end="", flush=True)
                first_step = False
            else:
                print("  [Synthesizing security summary...]", end="", flush=True)

            try:
                response = self.gemini_client.models.generate_content(
                    model=self.config.gemini_model,
                    contents=self.conversation_history,
                    config=gen_config,
                )
            except Exception as e:
                print("\r" + " " * 45 + "\r", end="", flush=True)
                print(f"\n[Gemini Error] {e}\n")
                break

            # Clear the progress indicator line
            print("\r" + " " * 45 + "\r", end="", flush=True)

            # If Gemini returned content (either tool calls or final answer)
            if not response.candidates or not response.candidates[0].content:
                print("\n[Agent] (Received empty response from model)\n")
                break

            candidate_content = response.candidates[0].content
            self.conversation_history.append(candidate_content)

            # Check if Gemini decided to call one or more tools
            function_calls = response.function_calls

            if not function_calls:
                # No tool calls requested: Gemini has produced the final answer
                answer_text = response.text or ""
                print(f"\nAgent:\n{answer_text}\n")
                break

            # Gemini requested tool calls: execute all tools in parallel using asyncio.gather
            async def _run_single_tool(call) -> types.Part:
                print(f"  [Tool Calling: {call.name}()]")
                tool_args = call.args if isinstance(call.args, dict) else {}
                tool_output_str = await self.mcp_manager.execute_tool(
                    call.name, tool_args
                )

                # Parse JSON output or wrap in dictionary
                try:
                    structured_output = json.loads(tool_output_str)
                except Exception:
                    structured_output = {"output": tool_output_str}

                return types.Part.from_function_response(
                    name=call.name,
                    response={"result": structured_output},
                )

            # Run all requested function calls simultaneously
            response_parts = await asyncio.gather(
                *[_run_single_tool(call) for call in function_calls]
            )

            # Append tool execution results back into conversation history
            self.conversation_history.append(
                types.Content(
                    role="user",
                    parts=response_parts,
                )
            )
            # The while loop continues so Gemini can inspect tool results and formulate answer


def main() -> None:
    """Entry point for running the Security Agent CLI."""
    agent = SecurityAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
