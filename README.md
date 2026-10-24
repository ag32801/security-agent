# Windows Security AI Agent (Gemini + MCP)

A modular, local AI agent built with **Google Gemini** (via the official `google-genai` SDK) and the **Model Context Protocol (MCP)** using `FastMCP`. The agent monitors your Windows laptop's security posture through strictly read-only, audited tools.

---

## Architecture Overview

```
User (CLI)
   │
   ▼
Agent Loop (agent/main.py)
   ├── Google Gemini LLM (reasons & decides which tools to call)
   └── MCP Client Manager (agent/mcp_client.py)
         │  (JSON-RPC over stdio)
         ▼
FastMCP Server (servers/laptop_security/server.py)
   ├── check_firewall_status   (PowerShell: Get-NetFirewallProfile)
   ├── check_defender_status   (PowerShell: Get-MpComputerStatus)
   └── Audit Logger            (logs/audit.log)
```

### Why MCP?
The Model Context Protocol (MCP) decouples the AI reasoning logic from the tools. The agent doesn't hardcode tool functions; instead, it dynamically connects to any server defined in `servers.json`. In future phases, you can add new servers (e.g. CVE lookup, network monitoring) without altering the agent's core codebase.

### Security Guarantees
- **Strictly Read-Only**: Tools only inspect system state. No settings can be changed, no files deleted, and no processes terminated.
- **Fixed Commands Only**: The LLM *never* generates PowerShell scripts. Every tool executes a predefined, immutable command literal.
- **Audit Logging**: Every single tool invocation is logged with an ISO timestamp and outcome to `logs/audit.log`.

---

## Project Structure

```
gemini-security-agent/
│
├── .env.example              <- Template for environment variables (API keys)
├── .gitignore                <- Protects secrets (.env), venv, and audit logs
├── requirements.txt          <- Pinned project dependencies
├── README.md                 <- This documentation file
├── servers.json              <- MCP Server registry
│
├── logs/
│   ├── .gitkeep              <- Keeps folder tracked in git
│   └── audit.log             <- Append-only tool call audit log
│
├── servers/                  <- MCP Servers
│   └── laptop_security/
│       ├── __init__.py
│       ├── server.py         <- FastMCP server running over stdio
│       └── tools.py          <- Fixed PowerShell commands & logging
│
└── agent/                    <- AI Agent Orchestrator
    ├── __init__.py
    ├── config.py             <- Configuration loader (.env, servers.json)
    ├── mcp_client.py         <- MCP Client (connects over stdio, fetches tools)
    └── main.py               <- Interactive CLI chat loop + Gemini function calling
```

---

## Prerequisites

- **Operating System**: Windows 10 or Windows 11
- **Python**: Version 3.11 or higher
- **Google Gemini API Key**: Free tier available from [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## Step-by-Step Setup

### 1. Open Terminal and Navigate to the Project
Open PowerShell or Command Prompt:
```powershell
cd d:\Projects\gemini-security-agent
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If script execution is disabled in PowerShell, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` or use `.\venv\Scripts\activate.bat` in CMD).*

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Your API Key
Copy the template `.env.example` file to create `.env`:
```powershell
cp .env.example .env
```
Open `.env` in any text editor and paste your Gemini API key:
```ini
GEMINI_API_KEY=AIzaSy...your_actual_key_here
GEMINI_MODEL=gemini-2.5-flash
```

---

## Testing Each Step

### Step A: Test PowerShell Tools Directly
Verify that your laptop allows querying the Windows Firewall and Defender:
```powershell
python -m servers.laptop_security.tools
```
**Expected Output**:
Prints JSON objects for both `check_firewall_status` and `check_defender_status`, and appends entries into `logs/audit.log`.

### Step B: Test the MCP Server & Client Integration
Verify that the MCP client can launch the server as a subprocess, discover the tools over `stdio`, and execute them:
```powershell
python -m agent.mcp_client
```
**Expected Output**:
```
Connecting to servers configured in servers.json...
[MCP] Discovered tool 'check_firewall_status' from server 'laptop_security'
[MCP] Discovered tool 'check_defender_status' from server 'laptop_security'

Discovered 2 total tool(s).
...
Result:
{ "status": "success", "firewall_all_profiles_enabled": true, ... }
...
All MCP sessions cleanly closed.
```

### Step C: Run the Full AI Agent
Start the interactive command-line assistant:
```powershell
python -m agent.main
```

**Example Conversation**:
```text
=================================================================
  Windows Laptop Security AI Agent (Gemini + MCP)
=================================================================
Connecting to local MCP security servers...
[MCP] Discovered tool 'check_firewall_status' from server 'laptop_security'
[MCP] Discovered tool 'check_defender_status' from server 'laptop_security'
[Ready] Discovered 2 security tool(s):
  • check_firewall_status
  • check_defender_status
[Model] Using Google Gemini: gemini-2.5-flash
Type 'exit' or 'quit' to close the agent.

You: Is my firewall and antivirus OK? Give me a short risk summary.
  [Tool Calling: check_firewall_status()]
  [Tool Calling: check_defender_status()]

Agent:
Here is your laptop's security risk summary:

• Windows Firewall: Active & Healthy. All three profiles (Domain, Private, and Public) are enabled.
• Microsoft Defender: Active & Healthy. Real-time protection and antivirus monitoring are enabled.
• Antivirus Signatures: Up to date (version 1.461.184.0).

Overall Risk: LOW. Your primary defenses are fully operational.
```

---

## Verifying the Audit Log
To inspect the record of every tool call executed on your system:
```powershell
Get-Content .\logs\audit.log -Tail 10
```

---

## How to Add New Tools in Later Phases

1. **Adding a Tool to an Existing Server**:
   - Add your fixed PowerShell function to `servers/laptop_security/tools.py`.
   - Register it with `@mcp.tool()` in `servers/laptop_security/server.py`.
   - That's it! The agent will automatically detect and use it next time it boots.

2. **Adding a New MCP Server (e.g., CVE lookup)**:
   - Create a new directory under `servers/cve_lookup/`.
   - Implement your server with FastMCP.
   - Add an entry to `servers.json`:
     ```json
     {
       "mcpServers": {
         "laptop_security": { ... },
         "cve_lookup": {
           "command": "python",
           "args": ["-m", "servers.cve_lookup.server"]
         }
       }
     }
     ```
   - The agent will connect to both servers simultaneously without needing code changes!
