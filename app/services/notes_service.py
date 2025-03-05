from typing import List, Dict, Any
import os
from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from supabase import create_client

from app.core.config import settings


class NotesResponse(BaseModel):
    notes: str

class NotesGeneration:
    def __init__(self, lecture_id: int):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)
        self.lecture_id = lecture_id
    
    def get_segments(self) -> List[Dict[str, Any]]:
        segments = self.supabase.table('segments').select(
            'id, content'
        ).eq('lecture_id', self.lecture_id).execute()
        return segments.data
    
    async def generate_notes(self) -> List[Dict[str, Any]]:
        segments = self.get_segments()
        all_segment_notes = []
    
        # Process each segment individually
        for segment in segments:
            segment_id = segment['id']
            segment_content = segment['content']

            print(f"Generating notes for segment {segment_id}...")
    
            # Create the prompt for OpenAI specific to this segment
            prompt = f"""
            Generate detailed notes based on the following content segment:
    
            Content: {segment_content}
    
            Create comprehensive, well-structured notes that capture the key points,
            concepts, and important details from this specific segment.
            """
    
            # Make the API call for this segment
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                response_format=NotesResponse,
                messages=[{"role": "user", "content": prompt}],
            )
    
            # Parse the response
            response_content = completion.choices[0].message.parsed
            all_segment_notes.append(
                {
                    "segment_id": segment_id,
                    "notes": response_content.notes
                }
            )
    
        return all_segment_notes
    

