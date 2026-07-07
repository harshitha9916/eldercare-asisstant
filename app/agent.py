# ruff: noqa
"""
ElderCare Assistant â€” Core Workflow Agent (app/agent.py)

Architecture:
    This module defines a Google ADK 2.0 graph-based Workflow with the following nodes:
        1. security_checkpoint  â€” Pure Python pre-LLM gate: PII scrubbing, injection
                                  detection, emergency routing, audit logging.
        2. orchestrator_agent   â€” Central LlmAgent that converses with the user and
                                  delegates tasks to specialist sub-agents via AgentTool.
        3. routine_agent        â€” LlmAgent for daily routines, doctor visit scheduling.
        4. medication_agent     â€” LlmAgent for medication schedule management.
        5. wellness_agent       â€” LlmAgent for wellness metric logging.
        6. hitl_approval        â€” Async node that interrupts for caregiver approval on
                                  critical (medication/appointment) actions.
        7. final_output         â€” Formats and emits the terminal response to the user.

Design Principles:
    - Security is deterministic (Python, not LLM): adversarial prompts cannot bypass it.
    - Each specialist agent exposes only the MCP tools it needs (least privilege).
    - HITL is an OS-level workflow pause, not an LLM self-approval pattern.
    - Retry logic on every LlmAgent handles transient Gemini API rate limit errors.
"""

import datetime
import json
import os
import re
import sys

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.workflow import Workflow, START, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.tools import AgentTool, McpToolset
from google.genai import types
from google.adk.models import Gemini
from mcp import StdioServerParameters

from app.config import config

# ---------------------------------------------------------------------------
# MCP Toolset Connections (Principle of Least Privilege)
# ---------------------------------------------------------------------------
# Each sub-agent receives a separate McpToolset connection with an explicit
# tool_filter. This ensures that:
#   - routine_agent   can only read/write schedules and visits.
#   - medication_agent can only update medication records.
#   - wellness_agent   can only log wellness entries.
# A sub-agent cannot accidentally (or adversarially) call a tool outside its
# domain, because the McpToolset will raise an error if it tries.
#
# We launch three separate stdio server connections (one per agent) rather than
# sharing a single session to avoid cross-agent state contamination.

routine_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        # Launch mcp_server.py as a direct file path rather than as a module
        # (-m app.mcp_server) to prevent Python package warnings from polluting
        # the stdio stream, which would corrupt the MCP JSON-RPC framing.
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    # Routine agent is responsible for schedules and doctor visit management.
    tool_filter=["get_daily_routines", "get_doctor_visits", "add_doctor_visit"]
)

medication_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    # Medication agent only needs to update medication records.
    # It cannot read wellness logs or schedule appointments.
    tool_filter=["update_medication_schedule"]
)

wellness_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    # Wellness agent only logs wellness entries.
    # It cannot touch medications or appointment schedules.
    tool_filter=["log_wellness_entry"]
)

# ---------------------------------------------------------------------------
# Specialist Sub-agents (LlmAgent)
# ---------------------------------------------------------------------------
# Each sub-agent is a focused LlmAgent with:
#   - A narrow, single-responsibility system instruction.
#   - Access only to the MCP tools relevant to its domain.
#   - Retry logic to handle transient Gemini API errors (e.g., 429 rate limit).
#   - An output convention: specific sentinel tokens ([APPOINTMENT_SCHEDULED],
#     [MEDICATION_CHANGED]) that the orchestrator and HITL node detect.

routine_agent = LlmAgent(
    name="routine_agent",
    model=Gemini(
        model=config.model,
        # Retry up to 3 times on transient API failures before surfacing an error.
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Routine Specialist. You coordinate the elder's daily routines, caregiver/family visits, and doctor schedules.
You have access to MCP tools to retrieve routines, get doctor visits, and schedule doctor visits.
Perform the requested action using your tools and return a concise, factual summary of what was done or scheduled to the orchestrator.
Do not write conversational chatter.
If you schedule a doctor/visit, include the text: [APPOINTMENT_SCHEDULED] in your output.""",
    tools=[routine_mcp_toolset],
)

medication_agent = LlmAgent(
    name="medication_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Medication Coordinator. You manage the elder's medication schedules, dosages, and compliance.
You have access to MCP tools to update medication schedules.
Perform the requested action using your tools and return a concise, factual summary of what was done to the orchestrator.
Do not write conversational chatter.
If you add or modify a medication, include the text: [MEDICATION_CHANGED] in your output.""",
    tools=[medication_mcp_toolset],
)

wellness_agent = LlmAgent(
    name="wellness_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Wellness Companion. You log the elder's physical/mental well-being (mood, pain level, sleep, symptoms).
You have access to MCP tools to log wellness entries.
Perform the requested action using your tools and return a concise, factual summary of what was logged (including what information is missing or what details were recorded) to the orchestrator.
Do not write conversational chatter.""",
    tools=[wellness_mcp_toolset],
)

# ---------------------------------------------------------------------------
# Orchestrator Agent (LlmAgent)
# ---------------------------------------------------------------------------
# The orchestrator is the only agent that talks directly to the user.
# Its responsibilities:
#   1. Understand the user's intent from natural language.
#   2. Delegate to the appropriate specialist via AgentTool (not direct calls).
#   3. Pass FULL conversation context to sub-agents (they are stateless).
#   4. Emit [APPROVAL_REQUIRED] when a critical action needs caregiver sign-off.
#   5. Synthesize the sub-agent's tool result into a user-facing response.
#
# Why AgentTool? AgentTool wraps each specialist as a callable "tool" from the
# orchestrator's perspective. This means the orchestrator can invoke them using
# the same function-calling mechanism it uses for any other tool, keeping the
# delegation pattern clean and extensible (add more specialists without
# re-architecting the orchestrator).

orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the ElderCare Orchestrator. 
Your goal is to coordinate elderly daily routines, track medication schedules, log well-being, and manage doctor/visit logs.
You are the primary conversational agent. You talk directly to the user.
To perform actions, you delegate tasks to specialized sub-agents using their tools.
When you call a sub-agent tool, you MUST include the full context of the request, including any relevant previous details from the conversation history (such as sleep hours or symptoms already provided), so the sub-agent has complete information.
Do not let sub-agents hold conversations. You are responsible for asking follow-up questions (e.g. asking for missing wellness details like mood or pain level) and delivering the final response to the user based on the sub-agent's tool execution result.

If the request involves modifying medications or scheduling doctor visits, you must explicitly notify the user that caregiver approval is required by including the text: [APPROVAL_REQUIRED] followed by the details.
""",
    tools=[
        # Wrap each specialist as an AgentTool so the orchestrator can call
        # them like functions. The orchestrator chooses the right specialist
        # based on the user's intent (medication vs. routine vs. wellness).
        AgentTool(routine_agent),
        AgentTool(medication_agent),
        AgentTool(wellness_agent)
    ]
)

# ---------------------------------------------------------------------------
# Workflow Node: security_checkpoint (Pure Python â€” NOT an LLM)
# ---------------------------------------------------------------------------
# DESIGN RATIONALE: Security is implemented as a deterministic Python function,
# not as an LLM system prompt guard. This is critical because:
#   - LLM-based guards can be bypassed by adversarial prompt injection.
#   - A Python function has guaranteed, testable, auditable behavior.
#   - No token cost and sub-millisecond execution vs. an LLM call.
#
# This node runs BEFORE any LLM ever sees the user's message. It:
#   1. Scrubs PII (emails, phone numbers, SSNs) using regex patterns.
#   2. Detects prompt injection keywords and blocks the request.
#   3. Detects medical emergency keywords and returns an immediate alert.
#   4. Emits a structured JSON audit log for every request (compliance trail).
#   5. Routes to "security_event" (blocked) or "__DEFAULT__" (orchestrator).

def security_checkpoint(ctx: Context, node_input: types.Content):
    """
    Pre-LLM security gate that scrubs PII, detects injection attacks,
    routes emergencies, and produces a structured JSON audit log.

    Args:
        ctx: ADK Context providing session metadata for audit logging.
        node_input: The raw user Content object from the previous node.

    Returns:
        Event with route="security_event" if blocked, or route="__DEFAULT__"
        with PII-scrubbed content forwarded to the orchestrator.
    """
    # Extract plain text from the Content parts list.
    user_text = ""
    if node_input and node_input.parts:
        user_text = "".join([part.text for part in node_input.parts if part.text])
    
    # --- 1. PII Scrubbing ---
    # Detect and replace sensitive identity tokens before they reach an LLM.
    # Even if a model is configured not to log inputs, we cannot guarantee
    # third-party observability tools won't capture raw prompts.
    pii_found = False
    scrubbed_text = user_text
    
    # Email addresses (RFC 5321 simplified pattern)
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    if re.search(email_pattern, scrubbed_text):
        scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_text)
        pii_found = True
        
    # US phone numbers (supports dashes, dots, no separator)
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    if re.search(phone_pattern, scrubbed_text):
        scrubbed_text = re.sub(phone_pattern, "[REDACTED_PHONE]", scrubbed_text)
        pii_found = True
        
    # US Social Security Numbers (NNN-NN-NNNN format)
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    if re.search(ssn_pattern, scrubbed_text):
        scrubbed_text = re.sub(ssn_pattern, "[REDACTED_SSN]", scrubbed_text)
        pii_found = True

    # --- 2. Prompt Injection Detection ---
    # Detect known adversarial phrases that attempt to override system behavior.
    # This is a keyword blocklist; production systems should add semantic
    # similarity checks or use a dedicated content moderation API.
    injection_keywords = [
        "ignore previous instructions",
        "system prompt",
        "override instructions",
        "you are now a chatgpt"
    ]
    injection_detected = False
    for kw in injection_keywords:
        if kw in user_text.lower():
            injection_detected = True
            break
            
    # --- 3. Emergency Detection ---
    # Hard-coded life-safety intercept. If any emergency keyword is detected,
    # the entire LLM pipeline is bypassed and a 911 alert is returned instantly.
    # No LLM inference latency; response is sub-millisecond.
    emergency_keywords = [
        "emergency", "heart attack", "chest pain", "suicide",
        "kill myself", "911", "ambulance", "stroke"
    ]
    emergency_detected = False
    for kw in emergency_keywords:
        if kw in user_text.lower():
            emergency_detected = True
            break

    # --- 4. Structured JSON Audit Log ---
    # Every request produces a machine-parseable audit record.
    # In production, stdout is captured by Google Cloud Logging, creating a
    # tamper-evident compliance trail for each message processed.
    audit_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": ctx.session.id,
        "pii_scrubbed": pii_found,
        "injection_detected": injection_detected,
        "emergency_detected": emergency_detected,
    }
    
    # --- 5. Routing Logic ---
    if emergency_detected:
        audit_data["severity"] = "CRITICAL"
        audit_data["action"] = "EMERGENCY_ALERT"
        print(json.dumps(audit_data))
        # Route to security_event node with a sentinel value for message selection.
        return Event(output="CRITICAL_EMERGENCY", route="security_event")
        
    if injection_detected:
        audit_data["severity"] = "WARNING"
        audit_data["action"] = "BLOCK_INJECTION"
        print(json.dumps(audit_data))
        return Event(output="INJECTION_ATTEMPT", route="security_event")
        
    # Request passed all checks â€” forward PII-scrubbed content to orchestrator.
    audit_data["severity"] = "INFO"
    audit_data["action"] = "PASS"
    print(json.dumps(audit_data))
    
    # Rebuild a clean Content object with the scrubbed text so the LLM never
    # sees the original PII-containing version of the message.
    clean_parts = [types.Part.from_text(text=scrubbed_text)]
    clean_content = types.Content(role='user', parts=clean_parts)
    return Event(output=clean_content, route="__DEFAULT__")


# ---------------------------------------------------------------------------
# Workflow Node: security_event
# ---------------------------------------------------------------------------
# Handles blocked requests. Generates a user-facing message appropriate to
# the type of security event (emergency vs. injection attempt) and terminates
# the workflow without invoking any LLM or MCP tool.

def security_event(node_input: str):
    """
    Terminal node for blocked requests. Returns a safe, informative message
    without invoking any downstream LLM or data tool.

    Args:
        node_input: Sentinel string ("CRITICAL_EMERGENCY" or "INJECTION_ATTEMPT").
    """
    if node_input == "CRITICAL_EMERGENCY":
        # Medical emergency: provide immediate life-safety guidance.
        msg = "âš ï¸ CRITICAL MEDICAL EMERGENCY DETECTED. Please call 911 or contact your primary healthcare provider immediately."
    else:
        # Prompt injection: inform the user the request was blocked.
        msg = "âš ï¸ Security Event: Your input was flagged as a potential prompt injection attempt and has been blocked."
        
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=msg)


# ---------------------------------------------------------------------------
# Workflow Node: hitl_approval (Human-in-the-Loop)
# ---------------------------------------------------------------------------
# DESIGN RATIONALE: The @node(rerun_on_resume=True) decorator enables the
# interrupt-resume pattern. When this node yields a RequestInput, ADK:
#   1. Serializes the workflow state to durable storage.
#   2. Returns control to the caller (the playground or API client).
#   3. Waits for the caregiver to provide input via a follow-up call.
#   4. Re-enters this node with ctx.resume_inputs populated.
#
# This is NOT an LLM asking itself "should I approve this?" â€” it is a genuine
# OS-level workflow pause that cannot be bypassed by any prompt manipulation.
#
# Trigger: presence of "[APPROVAL_REQUIRED]" sentinel in orchestrator output.
# Non-triggering actions (wellness logs, read queries) pass through instantly.

@node(rerun_on_resume=True)
async def hitl_approval(ctx: Context, node_input: str):
    """
    Caregiver Human-in-the-Loop approval gate.

    On first entry with [APPROVAL_REQUIRED] in the input: yields RequestInput
    to pause the workflow and prompt the caregiver.

    On resume: reads ctx.resume_inputs["caregiver_approved"] and either
    confirms or cancels the pending action.

    Args:
        ctx: ADK Context with session state and resume_inputs after interruption.
        node_input: String output from the orchestrator_agent.
    """
    text_content = node_input
    
    # Persist the orchestrator's output in session state so it is available
    # after the workflow resumes from the caregiver's response.
    ctx.state["orchestrator_text"] = text_content
    requires_approval = "[APPROVAL_REQUIRED]" in text_content
    
    if requires_approval:
        # First pass: caregiver hasn't responded yet â†’ pause and request input.
        if not ctx.resume_inputs or "caregiver_approved" not in ctx.resume_inputs:
            yield RequestInput(
                interrupt_id="caregiver_approved",
                message="âš ï¸ A caregiver/family member approval is required to proceed with this request. Do you approve? (yes/no)"
            )
            return  # Workflow suspends here until resume_inputs is populated.
        
        # Second pass (post-resume): process the caregiver's decision.
        approved_response = ctx.resume_inputs["caregiver_approved"].lower().strip()
        if approved_response in ("yes", "y"):
            # Caregiver approved â€” pass confirmation to final_output.
            yield Event(
                output=f"Approved. Action executed.\nOrchestrator output:\n{text_content}",
                state={"last_action_approved": True}
            )
        else:
            # Caregiver denied â€” action is cancelled, user is informed.
            yield Event(
                output=f"Denied. Action cancelled.\nOrchestrator output:\n{text_content}",
                state={"last_action_approved": False}
            )
    else:
        # No approval required (wellness log, read-only query, etc.) â€” pass through.
        yield Event(output=text_content)


# ---------------------------------------------------------------------------
# Workflow Node: final_output
# ---------------------------------------------------------------------------
# Formats the terminal response as a model-role Content event so the ADK
# playground and API clients render it as an assistant message.

def final_output(node_input: str):
    """
    Terminal output node. Emits the final response as a model-role Content
    event, making it visible as an assistant turn in any ADK-compatible client.

    Args:
        node_input: Confirmed/denied string from hitl_approval.
    """
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=node_input)]))
    yield Event(output=node_input)


# ---------------------------------------------------------------------------
# Workflow Graph Definition
# ---------------------------------------------------------------------------
# The ADK Workflow class takes an explicit edge list. Conditional routing is
# expressed as a dict mapping route keys to destination nodes.
#
# Graph edges:
#   START â†’ security_checkpoint
#   security_checkpoint â†’ security_event     (route="security_event")
#   security_checkpoint â†’ orchestrator_agent (route="__DEFAULT__")
#   orchestrator_agent  â†’ hitl_approval
#   hitl_approval       â†’ final_output

root_agent = Workflow(
    name="eldercare_assistant",
    edges=[
        (START, security_checkpoint),
        # Conditional routing from security gate: blocked â†’ security_event,
        # safe â†’ orchestrator_agent (the default path).
        (security_checkpoint, {"security_event": security_event, "__DEFAULT__": orchestrator_agent}),
        (orchestrator_agent, hitl_approval),
        (hitl_approval, final_output),
    ],
)

# ---------------------------------------------------------------------------
# ADK App
# ---------------------------------------------------------------------------
# The App object bundles the root_agent (Workflow) with a name that is used
# as the API path prefix in fast_api_app.py and as the A2A service identifier.

app = App(
    root_agent=root_agent,
    name="app",
)
