from pydantic import BaseModel
from typing import List

class MediaAnalysisResponse(BaseModel):
    transcription: str
    summary: str
    topic: str
    description: str
    youtube_resources: List[dict]
    segments: List[dict]

class YouTubeResource(BaseModel):
    title: str
    url: str
    description: str