# ElderCare Assistant 👵👴

An intelligent, secure, and coordinator-driven multi-agent system designed to coordinate elderly daily routines, track medication compliance, manage doctor/visit logs, and monitor well-being.

## Features

- **ADK Multi-Agent System**: Uses an orchestrator agent that delegates specialized tasks to a Medication Coordinator, Routine Specialist, or Wellness Companion.
- **Model Context Protocol (MCP)**: Exposes local tool integrations for retrieving routines, logging well-being, and scheduling medical visits.
- **Caregiver Human-in-the-Loop (HITL)**: Requires explicit caregiver approval for critical actions (e.g., adding medications or scheduling doctor appointments).
- **Security Checkpoint Node**: Built-in PII redaction, prompt injection detection, critical emergency keywords routing, and structured JSON audit logging.

## Prerequisites

Before running the project, make sure you have:
- **Python 3.11 or higher**
- **uv**: Python package manager - [Install](https://docs.astral.sh/uv/getting-started/installation/)
- **Gemini API Key**: Get one from [Google AI Studio](https://aistudio.google.com/apikey)

## Quick Start

1. Clone this repository:
   ```bash
   git clone <repo-url>
   cd eldercare-assistant
   ```

2. Copy the example `.env` file and add your Gemini API key:
   ```bash
   cp .env.example .env
   # Add your key to GOOGLE_API_KEY
   ```

3. Install all dependencies:
   ```bash
   make install
   ```

4. Launch the local interactive playground:
   ```bash
   make playground
   ```
   The playground UI will open at [http://localhost:18081](http://localhost:18081).

---

## Architecture Diagram

```mermaid
graph TD
    START([User Query]) --> SecCheck{Security Checkpoint}
    
    %% Security Paths
    SecCheck -- Unsafe / Emergency --> SecEvent[Security Event Node]
    SecCheck -- Clean / Safe --> Orch[Orchestrator Agent]
    
    %% Orchestration Delegation
    Orch --> Tool1[AgentTool: Routine Agent]
    Orch --> Tool2[AgentTool: Medication Agent]
    Orch --> Tool3[AgentTool: Wellness Agent]
    
    %% MCP Server integration
    Tool1 -.-> MCP[MCP Server stdio]
    Tool2 -.-> MCP
    Tool3 -.-> MCP
    
    MCP -.-> tools["[get_daily_routines, update_medication_schedule, log_wellness_entry, get_doctor_visits, add_doctor_visit]"]
    
    %% Downstream Workflow
    Tool1 --> HITL{HITL Approval Node}
    Tool2 --> HITL
    Tool3 --> HITL
    
    %% HITL Pause
    HITL -- Approved / Not Needed --> Output[Final Output Node]
    HITL -- Denied --> Output
    HITL -- Interrupts --> Caregiver[Caregiver Response]
    Caregiver --> HITL
    
    Output --> END([Response to User])
```

---

## How to Run

- **Interactive Playground (Dev UI)**:
  - Run `make playground` (On Windows, run: `uv run adk web app --host 127.0.0.1 --port 18081 --reload_agents`).
- **Production Server**:
  - Run `make run` (Runs a FastAPI local web server on port 8000).

---

## Sample Test Cases

### Test Case 1: Add Medication Schedule (Triggers HITL)
- **Input**: `"Please add a new medication: Vitamin D3, 2000 IU, once daily in the morning."`
- **Expected Behavior**: The request is routed through the security check to the orchestrator, then delegated to the `medication_agent`. The agent flags the medication modification as requiring approval (`[APPROVAL_REQUIRED]`) and pauses at the HITL approval node.
- **Check**: The playground UI will prompt you to input caregiver approval:
  `⚠️ A caregiver/family member approval is required to proceed with this request. Do you approve? (yes/no)`
  Enter `yes` to see the medication successfully updated.

### Test Case 2: Schedule Doctor Visit (Triggers HITL)
- **Input**: `"Schedule a doctor visit with Dr. Adams next Monday at 2:00 PM."`
- **Expected Behavior**: The orchestrator delegates to `routine_agent`, which calls the `add_doctor_visit` tool. The agent flags the appointment as requiring approval and interrupts.
- **Check**: The playground UI displays the caregiver verification prompt. Type `yes` to finalize the scheduled appointment.

### Test Case 3: Log Physical Symptoms (No HITL)
- **Input**: `"Log that I slept 7 hours and had low pain today."`
- **Expected Behavior**: Delegated to `wellness_agent`, which uses the `log_wellness_entry` tool. No medication or doctor visits are updated, so it runs to completion without interruption.
- **Check**: The playground displays a message confirming that the wellness logs were updated successfully.

---

## Troubleshooting

1. **Gemini API Quota Error (`429`)**:
   - If the agent runs out of quota, open `.env` and set `GEMINI_MODEL=gemini-2.5-flash-lite` to use a lighter model with higher request limits.
2. **MCP Session Creation Failure**:
   - If the MCP server fails to connect, ensure that Python is executing `app/mcp_server.py` directly (using the `app/mcp_server.py` script path rather than module paths like `-m app.mcp_server`), to prevent package package warning output polluting the standard streams.
3. **Changes Not Reflecting on Windows**:
   - The Windows playground does not automatically hot-reload agents correctly. Stop the active process:
     ```powershell
     Get-Process -Id (Get-NetTCPConnection -LocalPort 18081, 8090 -ErrorAction SilentlyContinue).OwningProcess | Stop-Process -Force
     ```
     Then restart `make playground`.

---

## Push to GitHub

1. Create a new repo at https://github.com/new
   - Name: elderly-care-asisstant
   - Visibility: Public or Private
   - Do NOT initialize with README (you already have one)

2. In your terminal, navigate into your project folder:
   ```bash
   cd eldercare-assistant
   git init
   git add .
   git commit -m "Initial commit: eldercare-assistant ADK agent"
   git branch -M main
   git remote add origin https://github.com/harshitha9916/elderly-care-asisstant.git
   git push -u origin main
   ```

3. Verify .gitignore includes:
   ```text
   .env          ← your API key — must NEVER be pushed
   .venv/
   __pycache__/
   *.pyc
   .adk/
   ```

⚠ NEVER push .env to GitHub. Your API key will be exposed publicly.

---

## Assets

![Workflow Architecture](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/assets/architecture_diagram.png)

![Cover Page Banner](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/assets/cover_page_banner.png)

## Demo Script

The narration/script for demoing this project can be found in [DEMO_SCRIPT.txt](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/DEMO_SCRIPT.txt).
