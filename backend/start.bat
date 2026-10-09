@echo off
call conda activate elevator_kg
start "" "D:\Program Files\neo4j-community-2026.05.0\bin\neo4j" start
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
pause