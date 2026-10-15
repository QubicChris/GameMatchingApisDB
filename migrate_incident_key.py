"""
One-off migration: drop the uq_sofa_incident_fallback unique key.

That key covered (sofa_event_id, incident_type, time, reversed_period_time),
so two incidents of the same type in the same minute (e.g. a double
substitution) overwrote each other. Safe to run more than once.

Usage:
    python migrate_incident_key.py
Then reload incidents from the saved JSON:
    python load_sofa_json.py --all
"""
from sqlalchemy import text

from database import engine
from load_sofa_json import incident_fallback_key_exists

with engine.begin() as conn:
    if incident_fallback_key_exists(conn):
        conn.execute(text("ALTER TABLE sofa_incidents DROP INDEX uq_sofa_incident_fallback"))
        print("Dropped uq_sofa_incident_fallback from sofa_incidents.")
    else:
        print("uq_sofa_incident_fallback not present — nothing to do.")
