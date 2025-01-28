from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from app.core.config import settings
from app.services.embedding_service import EmbeddingService


class Message(BaseModel):
    text: str
    is_user: bool

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )


class SearchRequest(BaseModel):
    query: str
    lecture_id: int
    conversation_history: Optional[List[Message]] = None
    top_k: int = 3

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )

class SearchCourseRequest(BaseModel):
    query: str
    course_id: int
    conversation_history: Optional[List[Message]] = None
    top_k: int = 3

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )


class SearchCourseResponse(BaseModel):
    answer: str
    lectures: List[dict]

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )

class SearchResponse(BaseModel):
    answer: str
    segments: List[dict]

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )


class LectureSearchService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def search_and_explain_course(self,query: str, course_id: int,conversation_history: List[Message], top_k: int = 3):
        try:
            # Get relevant segments
            segments = self.embedding_service.search_course(query, course_id, top_k)

            # Create a prompt that includes conversation history
            conversation_context = "\n".join([
                f"{'User' if msg.is_user else 'Assistant'}: {msg.text}"
                for msg in conversation_history[-5:]  # Include last 5 messages for context
            ])

            context = "\n".join([f"Segment {i + 1}: {seg['summary']}"
                                 for i, seg in enumerate(segments)])

            prompt = f"""You are helping a user understand a lecture. Based on the conversation history and lecture segments, provide a comprehensive answer to the query.
    
        Previous conversation:
        {conversation_context}
    
        Current question: "{query}"
    
        Relevant lecture segments:
        {context}
    
        Please provide a direct and informative answer that takes into account both the conversation history and the lecture segments.
        Please provide the answer shortly and concisely. Don't include any formatting or additional information.
        If the question is not related to the lecture, Answer with "This question is not related to the lecture."
        
"""
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )

            segments_to_return = []

            if(response.choices[0].message.content != "This question is not related to the lecture."):
                segments_to_return = segments
            else:
                segments_to_return = []

            return {
                "answer": response.choices[0].message.content,
                "segments": segments_to_return
            }
        except Exception as e:
            print(f"Error in search_and_explain_course: {e}")
            return {
                "answer": "An error occurred while processing the request.",
                "segments": []
            }


    def search_and_explain(self, query: str, lecture_id: int, conversation_history: List[Message], top_k: int = 3):
        try:
            # Get relevant segments
            segments = self.embedding_service.search_lecture(query, lecture_id, top_k)

            # Create a prompt that includes conversation history
            conversation_context = "\n".join([
                f"{'User' if msg.is_user else 'Assistant'}: {msg.text}"
                for msg in conversation_history[-5:]  # Include last 5 messages for context
            ])

            context = "\n".join([f"Segment {i + 1}: {seg['content']}"
                                 for i, seg in enumerate(segments)])

            prompt = f"""You are helping a user understand a lecture. Based on the conversation history and lecture segments, provide a comprehensive answer to the query.
    
        Previous conversation:
        {conversation_context}
    
        Current question: "{query}"
    
        Relevant lecture segments:
        {context}
    
        Please provide a direct and informative answer that takes into account both the conversation history and the lecture segments.
        Please provide the answer shortly and concisely. Don't include any formatting or additional information.
        If the question is not related to the lecture, Answer with "This question is not related to the lecture."
"""

            # Get GPT response
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )

            segments_to_return = []
            if(response.choices[0].message.content != "This question is not related to the lecture."):
                segments_to_return = segments
            else:
                segments_to_return = []

            return {
                "answer": response.choices[0].message.content,
                "segments": segments_to_return
            }
        except Exception as e:
            print(f"Error in search_and_explain: {e}")
            return {
                "answer": "An error occurred while processing the request.",
                "segments": []
        }
