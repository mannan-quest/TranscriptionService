from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any

from app.core.config import settings
from app.services.embedding_service import EmbeddingService

import json


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
    web_search: bool

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
    webAnswer: str
    segments: List[dict]
    references: List[str]

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='allow'
    )

class LectureResponse(BaseModel):
    answer: str = Field(description="Answer based on lecture segments or high-level summary.")
    webAnswer: str = Field(description="Answer based on web search, if performed.")
    isSegmentsRequired: bool = Field(description="Whether lecture segments were used for the answer.")
    references: List[str] = Field(default_factory=list, description="List of reference URLs retrieved from web search.")

    
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


    def search_and_explain(self, query: str, lecture_id: int, conversation_history: List[Message], top_k: int = 3, web_search: bool = True) -> Dict[str, Any]:
        try:
            # Define schema
            schema = LectureResponse.model_json_schema()
            schema["required"] = list(schema["properties"].keys())
            schema["additionalProperties"] = False

            # Get lecture segments
            segments = self.embedding_service.search_lecture(query, lecture_id, top_k)

            # Prepare conversation context
            conversation_context = "\n".join([
                f"{'User' if msg.is_user else 'Assistant'}: {msg.text}"
                for msg in conversation_history[-5:]  # Only last 5 messages
            ])

            # Prepare lecture segments context
            context = "\n".join([f"Segment {i + 1}: {seg['content']}" for i, seg in enumerate(segments)])

            prompt = f"""
            You are assisting a user in understanding a lecture. Your task is to produce TWO SEPARATE answers:

            1. **Lecture Answer:** Only based on lecture segments and conversation history.
            2. **Web Answer:** Based on information retrieved from a web search (if web_search = true).

            ### Rules:

            1. **Lecture Relevance Check**:
                - If the entire query is unrelated to the lecture, set answer to: "This question is not related to the lecture." and do not generate a webAnswer.
                - If the query is partially related and partially unrelated, only answer the relevant part. Explicitly mention that unrelated parts were ignored.

            2. **General Lecture Queries**:
                - For queries like "Summarize the lecture" or "What is this lecture about?", DO NOT use lecture segments. Just provide a short high-level summary.
                - Set isSegmentsRequired to false.

            3. **Specific Lecture Queries**:
                - If the question is about specific parts of the lecture, use the lecture segments.
                - Set isSegmentsRequired to true.

            4. **Greetings & Farewells**:
                - For greetings (hi, hello) or farewells (thanks, bye), respond naturally. Leave webAnswer and references empty.

            5. **Mandatory Web Search Handling**:
                - ONLY perform web search if web_search = true AND the query is lecture related (whether general or specific).
                - DO NOT skip the web search just because you "know" the answer.
                - Even if the answer is sufficient, still generate a webAnswer separately using web information.
                - Return at least 3 web search references.

            ### Return Format:
            Respond strictly in this JSON format:

            {{
                "answer": "",
                "webAnswer": "",
                "isSegmentsRequired": true/false,
                "references": []
            }}

            Context for Answer:
            Previous Conversation:
            {conversation_context}

            User's Question:
            {query}

            Relevant Lecture Segments:
            {context}

            web_search:
            {web_search}
            """


            # Call GPT
            response = self.client.responses.create(
                model="gpt-4o",
                input=[{"role": "user", "content": prompt}],
                tools=[{"type": "web_search_preview"}] if web_search else [],
                temperature=0.7,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "lecture_response",
                        "schema": schema,
                        "strict": True
                    }
                }
            )

            # Parse the structured response
            parsed_response = LectureResponse.model_validate_json(response.output_text)

            # Optional Fallbacks:
            if not web_search:
                parsed_response.webAnswer = ""
                parsed_response.references = []

            # If web_search was requested but somehow returned no references
            if web_search and len(parsed_response.references) < 3:
                parsed_response.references = []  # fallback to empty
                parsed_response.webAnswer = "Web search did not return enough reliable information to provide an additional answer."

            # If segments were not used, remove them from final result
            if not parsed_response.isSegmentsRequired:
                segments = []

            return {
                "answer": parsed_response.answer,
                "webAnswer": parsed_response.webAnswer,
                "isSegmentsRequired": parsed_response.isSegmentsRequired,
                "segments": segments,
                "references": parsed_response.references
            }

        except Exception as e:
            print(f"Error in search_and_explain: {e}")
            return {
                "answer": "An error occurred while processing the request.",
                "webAnswer": "",
                "isSegmentsRequired": False,
                "segments": [],
                "references": []
            }
