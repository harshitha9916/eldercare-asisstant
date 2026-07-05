# Project Submission Write-up: ElderCare Assistant 👵👴

## Problem Statement
Caring for elderly relatives is a complex and high-stakes responsibility. Caregivers must balance daily routines, strictly coordinate critical medication schedules, log wellness metrics (symptoms, mood, physical states), and schedule multiple medical appointments. Miscommunication or medication errors can lead to serious health issues. There is a critical need for an automated, secure assistant that coordinates these tasks while keeping a human caregiver firmly in the loop to review and approve critical changes.

---

## Solution Architecture
Below is the system architecture of the ElderCare Assistant. It implements a secure check, forwards to a central orchestrator which delegates work to specialized agents using the Model Context Protocol (MCP) server, and integrates a Caregiver Human-in-the-Loop checkpoint before finalizing critical actions.

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

## Concepts Used

- **ADK 2.0 Workflow**: Built using graph-based routing in [agent.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/agent.py#L225-L235).
- **LlmAgent**: Defines multiple specialized sub-agents (`routine_agent`, `medication_agent`, `wellness_agent`, and `orchestrator_agent`) in [agent.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/agent.py#L38-L105).
- **AgentTool**: Enables the orchestrator to dynamically delegate queries to the specialist agents in [agent.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/agent.py#L97-L103).
- **MCP Server**: Implements stdio-based tool interactions for routine and medical logs in [mcp_server.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/mcp_server.py).
- **Security Checkpoint**: Implements PII scrubbing, prompt injection guards, and structured JSON audit logging in [agent.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/agent.py#L107-L177).
- **Agents CLI**: Project scaffolded, structured, and run using standard `agents-cli` commands.

---

## Security Design

1. **PII Scrubbing**: Automatically detects and redacts emails, phone numbers, and Social Security Numbers (SSNs) to protect the elder's and caregiver's identity.
2. **Prompt Injection Guard**: Detects adversarial attempts to override the system instructions and immediately blocks the prompt.
3. **Emergency Check**: Detects medical emergencies (e.g., stroke, chest pain) and intercepts the query immediately with emergency guidance (call 911), skipping standard LLM processing.
4. **Structured Audit Log**: Prints structured JSON audit logs for every user message, identifying actions taken and marking them with INFO, WARNING, or CRITICAL severity.

---

## MCP Server Design
The MCP server exposed in [mcp_server.py](file:///c:/Users/harsh/OneDrive/Documents/ADK_Workflow/eldercare-assistant/app/mcp_server.py) provides 5 high-fidelity tools:
- `get_daily_routines`: Lists daily routine schedule.
- `update_medication_schedule`: Adds/updates medication records.
- `log_wellness_entry`: Logs mood, pain level, sleep, and symptoms.
- `get_doctor_visits`: Returns the list of doctor/caregiver appointments.
- `add_doctor_visit`: Schedules doctor visits.

These tools are isolated and wired only to the specialized sub-agents that need them, ensuring strict principle of least privilege.

---

## Human-in-the-Loop (HITL) Flow
To prevent the AI from making unauthorized schedule updates or drug alterations, a Human-in-the-Loop validation is implemented in the `hitl_approval` node. If a sub-agent marks the output with `[APPROVAL_REQUIRED]`, the workflow yields a `RequestInput` which halts execution and prompts the caregiver for approval. It resumes only when a caregiver explicitly replies with `yes` or `no`.

---

## Demo Walkthrough

1. **Test Case 1: Add Medication (HITL)**
   - Query: *"Add medication Vitamin D3 2000 IU"*
   - Flow: `START` ➔ `security_checkpoint` ➔ `orchestrator_agent` ➔ `medication_agent` (calls `update_medication_schedule` tool) ➔ `hitl_approval` (yields `RequestInput` caregiving prompt) ➔ user inputs `yes` ➔ `final_output` (approved).
2. **Test Case 2: Schedule Doctor Visit (HITL)**
   - Query: *"Schedule a doctor visit with Dr. Adams next Monday at 2:00 PM"*
   - Flow: Routes to `routine_agent` which executes the `add_doctor_visit` tool and pauses for caregiver approval. Entering `yes` writes it to the log.
3. **Test Case 3: Daily Wellness Log (No HITL)**
   - Query: *"Log that I slept 7 hours and had low pain today."*
   - Flow: Delegated to `wellness_agent` which runs the `log_wellness_entry` tool and finishes immediately, since no medication/appointment updates require approval.

---

## Impact / Value Statement
ElderCare Assistant gives family members and caregivers peace of mind. It ensures the elder's daily schedule is adhered to and documented, while maintaining a failsafe caregiver-in-the-loop validation for all critical medical schedule updates. This reduces caregiver burnout, prevents medication mistakes, and maintains a secure audit log for professional medical reviews.
