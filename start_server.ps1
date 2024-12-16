# Set environment variables
$env:PYTHONPATH = "."
$env:WIDTH = "1140"
$env:HEIGHT = "715"

New-NetFirewallRule -DisplayName "Allow FastAPI 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow

# Start the FastAPI server
python -m uvicorn computer.main:app --host 0.0.0.0 --port 8000