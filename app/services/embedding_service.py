import os
from typing import List, Dict

from openai import OpenAI, embeddings
from supabase import create_client

from ..core.config import settings

class EmbeddingService:

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)

    def generate_course_embeddings(self, course_id: int):
        """Generate embeddings for all lectures in a course"""
        # 1. Get all lectures in the course
        lectures = self.supabase.table('lectures').select(
            'lecture_id, name, summary, segments(id, content)'
        ).eq('course_id', course_id).execute()

        if not lectures.data:
            raise ValueError(f"No lectures found for course ID {course_id}")

        # 2. Generate embeddings for each lecture of course
        for lecture in lectures.data:
            # Generate embedding using OpenAI's API
            embedding = self._get_embedding(lecture['summary'])

            # Update lecture with embedding in database
            self.supabase.table('lectures').update({
                'embedding': embedding
            }).eq('lecture_id', lecture['lecture_id']).execute()

        return f"Generated embeddings for {len(lectures.data)} lectures"

    def generate_embeddings(self, lecture_id: int):
        """Generate embeddings for all segments of a lecture"""
        # 1. Get lecture and its segments
        lecture = self.supabase.table('lectures').select(
            'lecture_id, name, transcription, segments(id, content)'
        ).eq('lecture_id', lecture_id).execute()

        if not lecture.data:
            raise ValueError(f"No lecture found with ID {lecture_id}")

        lecture_data = lecture.data[0]
        segments = lecture_data.get('segments', [])

        print('segments:', segments)

        # 2. Generate embeddings for each segment
        for segment in segments:
            # Generate embedding using OpenAI's API
            embedding = self._get_embedding(segment['content'])

            # Update segment with embedding in database
            self.supabase.table('segments').update({
                'embedding': embedding
            }).eq('id', segment['id']).execute()

        return f"Generated embeddings for {len(segments)} segments"


    def search_course(self, query: str, course_id: int, top_k: int = 3) -> List[Dict]:
        """Search for relevant lecture segments based on query"""
        # 1. Generate embedding for the query
        query_embedding = self._get_embedding(query)

        # 2. Perform similarity search using Supabase's vector similarity
        results = self.supabase.rpc(
            'match_lectures',
            {
                'query_embedding': query_embedding,
                'input_course_id': course_id,
                'match_threshold': 0.7,
                'match_count': top_k
            }
        ).execute()

        return results.data


    def search_lecture(self, query: str,lecture_id: int, top_k: int = 3) -> List[Dict]:
        """Search for relevant lecture segments based on query"""
        # 1. Generate embedding for the query
        query_embedding = self._get_embedding(query)

        # 2. Perform similarity search using Supabase's vector similarity
        results = self.supabase.rpc(
            'match_segments',
            {
                'query_embedding': query_embedding,
                'input_lecture_id': lecture_id,  # Added lecture_id parameter
                'match_threshold': 0.7,
                'match_count': top_k
            }
        ).execute()

        return results.data

    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a piece of text using OpenAI's API"""
        response = self.client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"
        )

        return response.data[0].embedding

