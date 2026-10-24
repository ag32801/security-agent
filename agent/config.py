"""Configuration loader for the Gemini Security Agent.

Loads environment variables from .env and MCP server definitions from servers.json.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Project Root is two levels up from agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env located at project root
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE)


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class AgentConfig:
    gemini_api_key: Optional[str]
    gemini_model: str
    gemini_thinking_level: str
    servers: Dict[str, MCPServerConfig]


def load_config() -> AgentConfig:
    """Loads and validates configuration from environment and servers.json.

    Returns:
        AgentConfig: The complete configuration object.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    # Gemini 3.8 Flash supports LOW, MEDIUM, HIGH. Default to LOW for maximum speed.
    raw_thinking = os.getenv("GEMINI_THINKING_LEVEL", "LOW").upper()
    if raw_thinking in ("MINIMAL", "OFF", "NONE", "0"):
        thinking_level = "LOW"
    else:
        thinking_level = raw_thinking

    # Read servers.json
    servers_file = PROJECT_ROOT / "servers.json"
    servers: Dict[str, MCPServerConfig] = {}

    if servers_file.exists():
        try:
            with open(servers_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_servers = data.get("mcpServers", {})
            for name, s_cfg in raw_servers.items():
                cmd = s_cfg.get("command", "python")

                # If command is 'python', resolve to current sys.executable
                # This ensures the MCP server subprocess runs inside the same virtual environment
                if cmd in ("python", "python3"):
                    cmd = sys.executable

                args = s_cfg.get("args", [])
                env = s_cfg.get("env", {})

                servers[name] = MCPServerConfig(
                    name=name,
                    command=cmd,
                    args=args,
                    env=env,
                )
        except Exception as e:
            print(f"[Warning] Error loading {servers_file}: {e}")
    else:
        print(f"[Warning] Configuration file {servers_file} not found.")

    return AgentConfig(
        gemini_api_key=api_key,
        gemini_model=model_name,
        gemini_thinking_level=thinking_level,
        servers=servers,
    )
