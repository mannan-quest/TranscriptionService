from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import media_processing

app = FastAPI(title="Media Analysis API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(media_processing.router, prefix="/api/v1")