# Set environment variables
$env:PYTHONPATH = "."
$env:WIDTH = "1920"
$env:HEIGHT = "1080"

# Start the FastAPI server
python -m uvicorn computer.main:app --host 0.0.0.0 --port 8000