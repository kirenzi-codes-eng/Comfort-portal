from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Comfort Portal PWA Server",
    version="1.0.0",
)
 
# Allow requests from your Streamlit app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # We'll tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Comfort Portal PWA",
    }


@app.get("/logo.png")
def logo():
    return FileResponse(
        STATIC_DIR / "logo.png",
        media_type="image/png",
    )