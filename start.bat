@echo off
rem Serves this folder locally and opens the leaderboard. Close this window to stop.
cd /d "%~dp0"
start "" http://localhost:8000/index.html
python -m http.server 8000
