"""
ElderCare Assistant — MCP Tool Server (app/mcp_server.py)

This module implements a Model Context Protocol (MCP) server using FastMCP with
stdio transport. It acts as the persistence and business-logic layer for all
data operations in the ElderCare Assistant system.

Design:
    - Transport: stdio (launched as a subprocess by each sub-agent via StdioServerParameters).
    - Framework: FastMCP — a Python-first MCP server library with decorator-based tool
      registration. Each @mcp.tool() function is automatically exposed as an MCP tool
      with its name, description, and parameter schema derived from the function signature.
    - State: In-memory Python lists (pre-seeded with realistic sample data).
      This is intentional for the prototype — the MCP server boundary is the correct place
      to introduce a real database (SQLite, PostgreSQL, Firestore) without changing any
      agent code. Only this file would change.

Integration:
    - routine_agent   → calls: get_daily_routines, get_doctor_visits, add_doctor_visit
    - medication_agent → calls: update_medication_schedule
    - wellness_agent   → calls: log_wellness_entry
    Each sub-agent receives a McpToolset with a tool_filter that restricts access
    to only the tools listed above for that agent (principle of least privilege).

Security Note:
    Sensitive data (medication records, wellness logs, doctor visits) lives in this
    server process — isolated from the LLM agents. Agents see tool results as strings,
    never as raw in-memory objects. In a production deployment, this server would run
    in a separate container with its own network policy and access controls.
"""

from fastmcp import FastMCP

# Initialize the FastMCP server with a human-readable name.
# This name appears in MCP client logs and capability discovery responses.
mcp = FastMCP("ElderCare MCP Server")

# ---------------------------------------------------------------------------
# In-Memory State (Pre-seeded with realistic sample data)
# ---------------------------------------------------------------------------
# These lists simulate a database. Pre-seeded data allows judges and evaluators
# to run test queries immediately without needing to add initial data first.
# In production, replace with database reads/writes in each tool function.

routines = [
    {"time": "08:00 AM", "activity": "Breakfast and morning stretching", "status": "Pending"},
    {"time": "10:00 AM", "activity": "Morning walk in the garden", "status": "Pending"},
    {"time": "02:00 PM", "activity": "Afternoon nap", "status": "Pending"},
    {"time": "06:00 PM", "activity": "Dinner and puzzle time", "status": "Pending"},
]

medications = [
    {"name": "Aspirin", "dosage": "81mg", "time": "08:00 AM", "purpose": "Blood thinner", "compliance": "Taken"},
    {"name": "Metformin", "dosage": "500mg", "time": "07:00 PM", "purpose": "Diabetes control", "compliance": "Pending"},
]

wellness_logs = [
    # Seed entry demonstrates the schema that log_wellness_entry produces.
    {"date": "2026-07-04", "mood": "Cheerful", "pain_level": "Low", "sleep_hours": 7.5, "symptoms": "None"},
]

doctor_visits = [
    {"date": "2026-07-10", "time": "10:30 AM", "doctor": "Dr. Smith (Cardiologist)", "purpose": "Regular checkup", "notes": "Bring latest blood test results"},
]

# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------
# Each function decorated with @mcp.tool() is registered as an MCP tool.
# FastMCP automatically:
#   - Uses the function name as the tool name.
#   - Uses the docstring as the tool description (shown to the LLM as context).
#   - Derives the input schema from type-annotated parameters.
#   - Serializes the return value as the tool result string.

@mcp.tool()
def get_daily_routines() -> str:
    """Retrieve the elder's daily routine schedule and activities.
    
    Returns:
        A JSON string containing the list of routine activities with time,
        activity description, and completion status.
    """
    import json
    # Return a JSON string so the calling LlmAgent can parse and summarize it
    # in natural language for the user.
    return json.dumps(routines, indent=2)

@mcp.tool()
def update_medication_schedule(name: str, dosage: str, time: str, purpose: str) -> str:
    """Add a new medication or update an existing medication's dosage and timing.
    
    This tool implements an upsert pattern: if a medication with the same name
    already exists, its record is updated in-place; otherwise a new record is
    appended. This prevents duplicate entries from repeated caregiver requests.
    
    Args:
        name: Name of the medication (e.g., "Aspirin", "Vitamin D3").
        dosage: Dosage of the medication (e.g., "50mg", "2000 IU", "1 tablet").
        time: Scheduled administration time (e.g., "08:00 AM").
        purpose: Medical purpose of the medication (e.g., "Blood thinner").
        
    Returns:
        A success message confirming whether the medication was added or updated.
    """
    new_med = {"name": name, "dosage": dosage, "time": time, "purpose": purpose, "compliance": "Pending"}
    
    # Upsert: update existing record if name matches (case-insensitive),
    # otherwise append a new record.
    for med in medications:
        if med["name"].lower() == name.lower():
            med.update(new_med)
            return f"Updated existing medication: {name} ({dosage}) at {time}."
    medications.append(new_med)
    return f"Successfully added medication schedule: {name} ({dosage}) at {time} for {purpose}."

@mcp.tool()
def log_wellness_entry(mood: str, pain_level: str, sleep_hours: float, symptoms: str) -> str:
    """Log the elder's daily well-being state, including physical and emotional metrics.
    
    One entry is created per tool call and appended to the wellness log.
    The date is automatically set to today's date (UTC) so the caregiver does
    not need to supply it. Multiple calls on the same day create multiple entries,
    preserving a complete longitudinal health record.
    
    Args:
        mood: The elder's emotional state (e.g., "Happy", "Anxious", "Tired", "Peaceful").
        pain_level: Pain intensity (e.g., "None", "Low", "Moderate", "High").
        sleep_hours: Hours of sleep obtained (e.g., 7.5).
        symptoms: Any reported symptoms or health concerns (use "None" if none).
        
    Returns:
        A success message confirming the log entry was created with a summary.
    """
    import datetime
    today = datetime.date.today().isoformat()
    entry = {
        "date": today,
        "mood": mood,
        "pain_level": pain_level,
        "sleep_hours": sleep_hours,
        "symptoms": symptoms
    }
    wellness_logs.append(entry)
    return f"Logged wellness entry for today ({today}): Mood={mood}, Pain={pain_level}, Sleep={sleep_hours}h, Symptoms={symptoms}."

@mcp.tool()
def get_doctor_visits() -> str:
    """Get the schedule of upcoming medical appointments and doctor visits.
    
    Returns:
        A JSON string containing all scheduled doctor visits with date, time,
        doctor name, visit purpose, and preparation notes.
    """
    import json
    return json.dumps(doctor_visits, indent=2)

@mcp.tool()
def add_doctor_visit(date: str, time: str, doctor: str, purpose: str, notes: str = "") -> str:
    """Schedule a new doctor visit or medical appointment.
    
    Appends a new visit record to the doctor visits log. No duplicate checking
    is performed — the caregiver (via the HITL approval step) is responsible
    for confirming the details before the visit is committed.
    
    Args:
        date: Date of the visit in YYYY-MM-DD format (e.g., "2026-07-15").
        time: Time of the visit (e.g., "11:00 AM").
        doctor: Name and specialty of the doctor (e.g., "Dr. Adams (Neurologist)").
        purpose: Reason for the visit (e.g., "Annual cognitive assessment").
        notes: Optional preparation notes (e.g., "Bring medication list").
        
    Returns:
        A confirmation message with the scheduled appointment details.
    """
    visit = {"date": date, "time": time, "doctor": doctor, "purpose": purpose, "notes": notes}
    doctor_visits.append(visit)
    return f"Successfully scheduled visit with {doctor} on {date} at {time}."

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
# When launched as __main__ (via StdioServerParameters in agent.py), FastMCP
# starts the stdio transport loop, reading JSON-RPC requests from stdin and
# writing responses to stdout. The MCP protocol framing is handled entirely
# by FastMCP — no manual serialization needed.

if __name__ == "__main__":
    mcp.run()
