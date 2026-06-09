from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys

app = FastAPI(title="GDS Coder Backend Service")

# VERY IMPORTANT: This allows your frontend workspace to query the backend 
# without triggering annoying browser security blockades (CORS errors).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In a real system we would restrict this, but perfect for a sandbox!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "🚀 Greetings from the secure Coder Python backend!",
        "python_version": sys.version
    }

@app.get("/api/data")
def get_dummy_data():
    return {
        "items": [
            {"id": 1, "name": "GDS Alpha Task Alpha", "complete": True},
            {"id": 2, "name": "Verify Coder Multi-Workspace Routing", "complete": False}
        ]
    }
