from typing import List, Dict, Any
import os
from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from supabase import create_client

from app.core.config import settings


class Quiz(BaseModel):
    questions: List[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "answer": {"type": "string"},
                            "options": {"type": "array", "items": {"type": "string"}},
                            "explanation": {"type": "string"},
                        },
                        "required": ["question", "answer", "options"],
                    },
                },
            },
            "required": ["questions"],
        }


class FlashCardResponse(BaseModel):
    flashcards: List[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "type": "object",
            "properties": {
                "flashcards": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "front": {"type": "string"},
                            "back": {"type": "string"},
                            "color": {"type": "string"},
                            "text": {"type": "string"}
                        },
                        "required": ["front", "back"],
                    },
                },
            },
            "required": ["flashcards"],
        }

class QuizGeneration:
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

    async def generate_quiz(self, difficulty: str) -> List[Dict[str, Any]]:
        segments = self.get_segments()

        # Combine all segments content
        whole_content = ' '.join(segment['content'] for segment in segments)

        # Create the prompt for OpenAI
        prompt = f"""
        Generate a multiple choice quiz based on this content:
        Content: {whole_content}
        Difficulty: {difficulty}

        Requirements:
        - Generate 10 multiple choice questions
        - Each question should test understanding, not just memorization
        - Each question should have 4 options including the correct answer
        - Options should be distinct and plausible
        - Provide an explanation for each question's answer

        """

        # Make the API call
        completion =  self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # Adjust model name to whatever is valid in your environment
            response_format=Quiz,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse the response into our Pydantic model
        response_content = completion.choices[0].message.parsed

        return response_content.questions


    async def generate_flashcards(self):
        segments = self.get_segments()

        # Combine all segments content
        whole_content = ' '.join(segment['content'] for segment in segments)

        # Create the prompt for OpenAI
        prompt = f"""
        You are creating flashcards designed to enhance both understanding and memorization of the provided content. Each flashcard should be structured effectively to reinforce key concepts, definitions, and critical insights.

- The front can present a key idea, question, term, or concept.
- The back should provide a clear, concise, and meaningful explanation, summary, or answer that promotes deeper comprehension.
- The flashcards should vary in format, including direct questions, fill-in-the-blanks, and conceptual explanations, making learning engaging.
- Assign a color to each flashcard that complements its theme. The colors should be visually appealing yet not too bright, making them easy on the eyes. The color should be specified in the HEX format (e.g., #FF5733).
- Assign a text color to each flash card considering its color you are chasing, it's either going to be black or white.
- Task:
    -  Generate 10 well-structured flashcards based on the content below:

Content: {whole_content}

Each flashcard should be designed to optimize retention while ensuring the learner gains a strong grasp of the subject matter.
        """

        # Make the API call
        completion =  self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # Adjust model name to whatever is valid in your environment
            response_format=FlashCardResponse,
            messages=[{"role": "user", "content": prompt}],
        )

        response_content = completion.choices[0].message.parsed

        return  response_content.flashcards
