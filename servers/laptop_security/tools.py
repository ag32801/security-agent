"""Read-only Windows security tools and audit logging.

Security Rules:
- All commands are fixed string literals.
- No dynamic string interpolation or LLM-supplied shell execution.
- Every invocation is recorded in logs/audit.log with a timestamp.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List

# Locate the project root relative to this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
AUDIT_LOG_FILE = LOGS_DIR / "audit.log"


def log_tool_call(tool_name: str, status: str, details: str = "") -> None:
    """Appends an audit record of a tool invocation with an ISO timestamp.

    Args:
        tool_name: The name of the tool executed.
        status: SUCCESS or ERROR.
        details: Additional context or error message.
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_entry = (
            f"[{timestamp}] TOOL: {tool_name} | STATUS: {status} | DETAILS: {details}\n"
        )
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        # Failsafe: logging failure should not crash the tool, but print warning
        print(f"[Warning] Failed to write audit log: {e}")


def _parse_powershell_date(date_str: Any) -> str:
    """Converts PowerShell's JSON date format '/Date(1792837144000)/' to ISO string."""
    if not isinstance(date_str, str):
        return str(date_str)

    match = re.search(r"/Date\((\d+)\)/", date_str)
    if match:
        timestamp_ms = int(match.group(1))
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return date_str


def check_firewall_status() -> Dict[str, Any]:
    """Retrieves the status of Windows Firewall profiles (Domain, Private, Public).

    Executes a fixed, read-only PowerShell command:
    Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction

    Returns:
        A dictionary with the firewall profile states and a risk assessment hint.
    """
    tool_name = "check_firewall_status"
    # Fixed command string - NEVER concatenate user or LLM input into this
    fixed_ps_command = (
        "Get-NetFirewallProfile | "
        "Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction | "
        "ConvertTo-Json"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", fixed_ps_command],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        raw_data = json.loads(result.stdout)
        # Ensure raw_data is a list if only one profile returned
        profiles_list = raw_data if isinstance(raw_data, list) else [raw_data]

        # In PowerShell NetFirewallProfile:
        # DefaultInboundAction: 0 = NotConfigured, 1 = Block, 2 = Allow
        action_map = {0: "NotConfigured", 1: "Block", 2: "Allow"}

        parsed_profiles: List[Dict[str, Any]] = []
        all_enabled = True

        for p in profiles_list:
            # Enabled can be 1 (True), 0/2 (False), or a boolean
            is_enabled = bool(p.get("Enabled") == 1 or p.get("Enabled") is True)
            if not is_enabled:
                all_enabled = False

            raw_inbound = p.get("DefaultInboundAction")
            raw_outbound = p.get("DefaultOutboundAction")

            inbound_desc = action_map.get(raw_inbound, str(raw_inbound))
            outbound_desc = action_map.get(raw_outbound, str(raw_outbound))

            parsed_profiles.append({
                "profile": p.get("Name"),
                "enabled": is_enabled,
                "default_inbound_action": inbound_desc,
                "default_outbound_action": outbound_desc,
            })

        response = {
            "status": "success",
            "firewall_all_profiles_enabled": all_enabled,
            "profiles": parsed_profiles,
        }

        log_tool_call(
            tool_name,
            "SUCCESS",
            f"{len(parsed_profiles)} profiles checked. All enabled: {all_enabled}",
        )
        return response

    except subprocess.TimeoutExpired:
        err = "PowerShell command timed out after 15 seconds."
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}
    except subprocess.CalledProcessError as e:
        err = f"PowerShell returned non-zero exit code: {e.stderr.strip()}"
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}
    except Exception as e:
        err = f"Unexpected error while querying firewall: {str(e)}"
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}


def check_defender_status() -> Dict[str, Any]:
    """Retrieves Microsoft Defender real-time protection status and signature updates.

    Executes a fixed, read-only PowerShell command:
    Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled, AntivirusEnabled, AntispywareEnabled, AntivirusSignatureLastUpdated, AntivirusSignatureVersion

    Returns:
        A dictionary containing real-time protection status and signature details.
    """
    tool_name = "check_defender_status"
    # Fixed command string - NEVER concatenate user or LLM input into this
    fixed_ps_command = (
        "Get-MpComputerStatus | "
        "Select-Object RealTimeProtectionEnabled, AntivirusEnabled, AntispywareEnabled, "
        "AntivirusSignatureLastUpdated, AntivirusSignatureVersion | "
        "ConvertTo-Json"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", fixed_ps_command],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        data = json.loads(result.stdout)
        signature_date_raw = data.get("AntivirusSignatureLastUpdated")
        readable_date = _parse_powershell_date(signature_date_raw)

        real_time_enabled = bool(data.get("RealTimeProtectionEnabled", False))
        antivirus_enabled = bool(data.get("AntivirusEnabled", False))
        antispyware_enabled = bool(data.get("AntispywareEnabled", False))
        signature_version = data.get("AntivirusSignatureVersion", "Unknown")

        is_healthy = real_time_enabled and antivirus_enabled and antispyware_enabled

        response = {
            "status": "success",
            "is_healthy": is_healthy,
            "real_time_protection_enabled": real_time_enabled,
            "antivirus_enabled": antivirus_enabled,
            "antispyware_enabled": antispyware_enabled,
            "signature_last_updated": readable_date,
            "signature_version": signature_version,
        }

        log_tool_call(
            tool_name,
            "SUCCESS",
            f"Health: {is_healthy}, Version: {signature_version}, Updated: {readable_date}",
        )
        return response

    except subprocess.TimeoutExpired:
        err = "PowerShell command timed out after 15 seconds."
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}
    except subprocess.CalledProcessError as e:
        err = f"PowerShell returned non-zero exit code: {e.stderr.strip()}"
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}
    except Exception as e:
        err = f"Unexpected error while querying Windows Defender: {str(e)}"
        log_tool_call(tool_name, "ERROR", err)
        return {"status": "error", "error": err}


if __name__ == "__main__":
    # Self-test when executed directly
    print("Testing check_firewall_status()...")
    fw = check_firewall_status()
    print(json.dumps(fw, indent=2))

    print("\nTesting check_defender_status()...")
    def_stat = check_defender_status()
    print(json.dumps(def_stat, indent=2))
