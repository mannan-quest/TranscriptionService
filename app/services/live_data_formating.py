from openai import AsyncOpenAI

from app.core.config import settings
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel,Field

class NoteType(str, Enum):
    text = "text"
    audio = "audio"
    image = "image"
    pdf = "pdf"

# Pydantic model for a Note
class Note(BaseModel):
    type: NoteType
    content: str
    createdAt: datetime

# Pydantic model for a Transcribed Sentence
class TranscribedSentence(BaseModel):
    text: str
    startTime: datetime
    endTime: Optional[datetime] = None
    notes: List[Note] = Field(default_factory=list)

# Pydantic model for the incoming request body
class AnalyzeLiveMediaRequest(BaseModel):
    sentences: List[TranscribedSentence]
    course_id: int

class AnalysisResult(BaseModel):
    topics: List[Dict[str, Any]]
    overall_topic: str
    overall_summary: str
    overall_description: str

    class Config:
        json_schema_extra = {
            "type": "object",
            "properties": {
                "overall_topic": {"type": "string"},
                "overall_summary": {"type": "string"},
                "overall_description": {"type": "string"},
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "description": {"type": "string"},
                            "summary": {"type": "string"},
                            "translation": {"type": "string"},
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                        },
                        "required": [
                            "topic",
                            "description",
                            "summary",
                            "translation",
                            "start_time",
                            "end_time"
                        ],
                    },
                },
            },
            # "required" MUST list every field you declared
            "required": [
                "topics",
                "overall_topic",
                "overall_summary",
                "overall_description"
            ]
        }



class LiveDataFormating:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def format_data(self, data:AnalyzeLiveMediaRequest):

        prompt = f"""
            You are give list of sentences with start and end time, text of sentence and notes.
            Your job is to join all the sentences and do following things for data:
             - fill in the gaps necessary to complete the text,
             - summarize the text
             - find description of text
             - find the topic for whole conversation 
             - make meaningful segments of text and consider below things for segments
        1. For each segment, you need to consider below things:
            - A segment should be at least 120 seconds/2 minutes long.
            - Translate the text within each segment to English.
            - A segment should be a complete thought or idea.
            - Segment should not be short, its very important to keep the segment long enough.
        2. For each topic/segment, return:
           - "topic" (short name of the topic)
           - "description" (a few lines describing the topic)
           - "summary" (a short summary in English)
           - "translation" (verbatim English translation of the text within that segment)
           - "start_time" (earliest start time for this chunk)
           - "end_time" (latest end time for this chunk)
        3. For each topic/segment translation, consider the following:
           - Provide the *verbatim* text (English translation) for that portion.
           - Do not summarize or shorten the translation.
           - Avoid using ellipses ( ... ) to indicate omitted text.
           - If you reach a token limit, continue splitting the response but ensure no text is omitted.
            
        Structure your final JSON exactly like this:
        {{
          "overall_topic": "...",
          "overall_summary": "...",
          "overall_description": "...",
          "topics": [
             {{
               "topic": "...",
               "description": "...",
               "summary": "...",
               "translation": "...",
               "start_time": 0,
               "end_time": 300
             }},
             ...
          ]
        }}

        Sentences:
        {data}
        """

        response = await self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # Adjust model name to whatever is valid in your environment
            response_format=AnalysisResult,  # Our Pydantic model
            messages=[{"role": "user", "content": prompt}]
        )

        parsed_data = response.choices[0].message.parsed

        return parsed_data



