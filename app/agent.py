# ruff: noqa
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

# Define McpToolsets with filtered tools for each sub-agent
routine_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    tool_filter=["get_daily_routines", "get_doctor_visits", "add_doctor_visit"]
)

medication_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    tool_filter=["update_medication_schedule"]
)

wellness_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["app/mcp_server.py"],
    ),
    tool_filter=["log_wellness_entry"]
)

# Specialized Sub-agents
routine_agent = LlmAgent(
    name="routine_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Routine Specialist. You coordinate the elder's daily routines, family/caregiver visits, and schedules. 
You have access to MCP tools to retrieve daily routines, get doctor visits, and schedule doctor visits.
When asked to schedule a doctor visit or general visit, use the appropriate tools to do so. 
State what you have scheduled in your response. If an appointment is scheduled, clearly state: [APPOINTMENT_SCHEDULED].""",
    tools=[routine_mcp_toolset],
)

medication_agent = LlmAgent(
    name="medication_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Medication Coordinator. You manage the elder's medication schedules, dosages, alerts, and compliance.
You have access to MCP tools to update medication schedules. Use them whenever you need to add or update medication.
If asked to add or change medication, explain the change clearly and note that a caregiver approval is required.
Always highlight side effects or drug interaction warnings if any. If a medication is added or modified, clearly state: [MEDICATION_CHANGED].""",
    tools=[medication_mcp_toolset],
)

wellness_agent = LlmAgent(
    name="wellness_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Wellness Companion. You log the elder's physical/mental well-being, mood, physical symptoms, pain level, sleep quality, and general state.
You have access to MCP tools to log wellness entries. Use them whenever wellness logs or physical states need to be saved.
Help provide gentle advice or log the symptoms for the doctor's review. Highlight any significant health warnings.""",
    tools=[wellness_mcp_toolset],
)

orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the ElderCare Orchestrator. 
Your goal is to coordinate elderly daily routines, track medication schedules, log well-being, and manage doctor/visit logs.
For any query, identify which of the specialized sub-agents is best suited to handle the task, and delegate to them:
- Use routine_agent to manage daily schedules, routines, caregiver/family visits, and doctor/medical appointments.
- Use medication_agent to handle medication schedules, reminders, dosages, and compliance.
- Use wellness_agent to log physical/mental health state, mood, symptoms, and wellness.

If the request involves modifying medications (like adding a new drug, changing a dosage) or scheduling a new doctor/medical appointment, you must explicitly notify the user that caregiver approval is required. In your response, include the text: [APPROVAL_REQUIRED] followed by the details of the request.
""",
    tools=[
        AgentTool(routine_agent),
        AgentTool(medication_agent),
        AgentTool(wellness_agent)
    ]
)

# Workflow Function Nodes

def security_checkpoint(ctx: Context, node_input: types.Content):
    # Extract text from user input
    user_text = ""
    if node_input and node_input.parts:
        user_text = "".join([part.text for part in node_input.parts if part.text])
    
    # 1. PII Scrubbing (Phone, Email, SSN)
    pii_found = False
    scrubbed_text = user_text
    
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    if re.search(email_pattern, scrubbed_text):
        scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_text)
        pii_found = True
        
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    if re.search(phone_pattern, scrubbed_text):
        scrubbed_text = re.sub(phone_pattern, "[REDACTED_PHONE]", scrubbed_text)
        pii_found = True
        
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    if re.search(ssn_pattern, scrubbed_text):
        scrubbed_text = re.sub(ssn_pattern, "[REDACTED_SSN]", scrubbed_text)
        pii_found = True

    # 2. Prompt Injection Detection
    injection_keywords = ["ignore previous instructions", "system prompt", "override instructions", "you are now a chatgpt"]
    injection_detected = False
    for kw in injection_keywords:
        if kw in user_text.lower():
            injection_detected = True
            break
            
    # 3. Domain-Specific Rule: Emergency Detection
    emergency_keywords = ["emergency", "heart attack", "chest pain", "suicide", "kill myself", "911", "ambulance", "stroke"]
    emergency_detected = False
    for kw in emergency_keywords:
        if kw in user_text.lower():
            emergency_detected = True
            break

    # 4. Structured JSON Audit Log
    audit_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": ctx.session.id,
        "pii_scrubbed": pii_found,
        "injection_detected": injection_detected,
        "emergency_detected": emergency_detected,
    }
    
    if emergency_detected:
        audit_data["severity"] = "CRITICAL"
        audit_data["action"] = "EMERGENCY_ALERT"
        print(json.dumps(audit_data))
        return Event(output="CRITICAL_EMERGENCY", route="security_event")
        
    if injection_detected:
        audit_data["severity"] = "WARNING"
        audit_data["action"] = "BLOCK_INJECTION"
        print(json.dumps(audit_data))
        return Event(output="INJECTION_ATTEMPT", route="security_event")
        
    audit_data["severity"] = "INFO"
    audit_data["action"] = "PASS"
    print(json.dumps(audit_data))
    
    clean_parts = [types.Part.from_text(text=scrubbed_text)]
    clean_content = types.Content(role='user', parts=clean_parts)
    return Event(output=clean_content, route="__DEFAULT__")


def security_event(node_input: str):
    if node_input == "CRITICAL_EMERGENCY":
        msg = "⚠️ CRITICAL MEDICAL EMERGENCY DETECTED. Please call 911 or contact your primary healthcare provider immediately."
    else:
        msg = "⚠️ Security Event: Your input was flagged as a potential prompt injection attempt and has been blocked."
        
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=msg)


@node(rerun_on_resume=True)
async def hitl_approval(ctx: Context, node_input: str):
    text_content = node_input
    
    ctx.state["orchestrator_text"] = text_content
    requires_approval = "[APPROVAL_REQUIRED]" in text_content
    
    if requires_approval:
        if not ctx.resume_inputs or "caregiver_approved" not in ctx.resume_inputs:
            yield RequestInput(
                interrupt_id="caregiver_approved",
                message="⚠️ A caregiver/family member approval is required to proceed with this request. Do you approve? (yes/no)"
            )
            return
        
        approved_response = ctx.resume_inputs["caregiver_approved"].lower().strip()
        if approved_response == "yes" or approved_response == "y":
            yield Event(
                output=f"Approved. Action executed.\nOrchestrator output:\n{text_content}",
                state={"last_action_approved": True}
            )
        else:
            yield Event(
                output=f"Denied. Action cancelled.\nOrchestrator output:\n{text_content}",
                state={"last_action_approved": False}
            )
    else:
        yield Event(output=text_content)


def final_output(node_input: str):
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=node_input)]))
    yield Event(output=node_input)


# Workflow Definition
root_agent = Workflow(
    name="eldercare_assistant",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"security_event": security_event, "__DEFAULT__": orchestrator_agent}),
        (orchestrator_agent, hitl_approval),
        (hitl_approval, final_output),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
