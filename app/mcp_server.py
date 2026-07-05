from fastmcp import FastMCP

# Initialize the FastMCP server
mcp = FastMCP("ElderCare MCP Server")

# Mock In-Memory Databases to keep track of state
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
    {"date": "2026-07-04", "mood": "Cheerful", "pain_level": "Low", "sleep_hours": 7.5, "symptoms": "None"},
]

doctor_visits = [
    {"date": "2026-07-10", "time": "10:30 AM", "doctor": "Dr. Smith (Cardiologist)", "purpose": "Regular checkup", "notes": "Bring latest blood test results"},
]

@mcp.tool()
def get_daily_routines() -> str:
    """Retrieve the elder's daily routine schedule and activities.
    
    Returns:
        A JSON string containing the list of routine activities.
    """
    import json
    return json.dumps(routines, indent=2)

@mcp.tool()
def update_medication_schedule(name: str, dosage: str, time: str, purpose: str) -> str:
    """Add a new medication or update an existing medication's dosage and timing.
    
    Args:
        name: Name of the medication.
        dosage: Dosage of the medication (e.g., 50mg, 1 tablet).
        time: Scheduled time (e.g., 08:00 AM).
        purpose: Medical purpose of the medication.
        
    Returns:
        A success message confirming the medication schedule update.
    """
    new_med = {"name": name, "dosage": dosage, "time": time, "purpose": purpose, "compliance": "Pending"}
    # Check if exists and update, else append
    for med in medications:
        if med["name"].lower() == name.lower():
            med.update(new_med)
            return f"Updated existing medication: {name} ({dosage}) at {time}."
    medications.append(new_med)
    return f"Successfully added medication schedule: {name} ({dosage}) at {time} for {purpose}."

@mcp.tool()
def log_wellness_entry(mood: str, pain_level: str, sleep_hours: float, symptoms: str) -> str:
    """Log the elder's daily well-being state, including physical and emotional metrics.
    
    Args:
        mood: The elder's emotional state (e.g., Happy, Anxious, Tired, Peaceful).
        pain_level: Pain intensity (e.g., None, Low, Moderate, High).
        sleep_hours: Hours of sleep obtained.
        symptoms: Any reported symptoms or health concerns.
        
    Returns:
        A success message indicating the log entry was created.
    """
    import datetime
    today = datetime.date.today().isoformat()
    entry = {"date": today, "mood": mood, "pain_level": pain_level, "sleep_hours": sleep_hours, "symptoms": symptoms}
    wellness_logs.append(entry)
    return f"Logged wellness entry for today ({today}): Mood={mood}, Pain={pain_level}, Sleep={sleep_hours}h, Symptoms={symptoms}."

@mcp.tool()
def get_doctor_visits() -> str:
    """Get the schedule of upcoming medical appointments and doctor visits.
    
    Returns:
        A JSON string of doctor visits.
    """
    import json
    return json.dumps(doctor_visits, indent=2)

@mcp.tool()
def add_doctor_visit(date: str, time: str, doctor: str, purpose: str, notes: str = "") -> str:
    """Schedule a new doctor visit or medical appointment.
    
    Args:
        date: Date of the visit (YYYY-MM-DD).
        time: Time of the visit (e.g., 11:00 AM).
        doctor: Name and specialty of the doctor.
        purpose: Reason for the visit.
        notes: Additional notes or preparations.
        
    Returns:
        A message confirming the scheduled appointment.
    """
    visit = {"date": date, "time": time, "doctor": doctor, "purpose": purpose, "notes": notes}
    doctor_visits.append(visit)
    return f"Successfully scheduled visit with {doctor} on {date} at {time}."

if __name__ == "__main__":
    mcp.run()
