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

class LectureResponse(BaseModel):
    answer: str = Field(description="The answer to the user's query")
    isSegmentsRequired: bool = Field(description="Whether segments should be included in the response")
    references: List[str] = Field(default_factory=list, description="List of reference URLs from web search")

    
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


    def search_and_explain(self, query: str, lecture_id: int, conversation_history: List[Message], top_k: int = 3, web_search: bool = False) -> Dict[str, Any]:
        try:
            # Get relevant segments
            schema = LectureResponse.model_json_schema()
            schema["required"] = list(schema["properties"].keys())
            schema["additionalProperties"] = False
            segments = self.embedding_service.search_lecture(query, lecture_id, top_k)

            # Create a prompt that includes conversation history
            conversation_context = "\n".join([
                f"{'User' if msg.is_user else 'Assistant'}: {msg.text}"
                for msg in conversation_history[-5:]  # Include last 5 messages for context
            ])

            context = "\n".join([f"Segment {i + 1}: {seg['content']}"
                                for i, seg in enumerate(segments)])

            prompt = f"""You are helping a user understand a lecture. Based on the conversation history and lecture segments, provide a **strictly relevant** answer to the query.

                ### **Guidelines:**
                1. **Strict Relevance to Lecture:**  
                - You MUST answer only based on the provided lecture segments and conversation history.  
                - If the query contains any part **not related to the lecture**, you **must ignore** the unrelated part and mention:  
                    **"I can only provide information related to the lecture."**  
                - If the **entire** query is unrelated to the lecture, respond with:  
                    **"This question is not related to the lecture."**

                2. **Handling of Mixed Queries:**  
                - If the query asks about both a relevant topic and an unrelated one, **ONLY** answer the relevant part and **completely ignore** the unrelated part.  
                - Example:  
                    **User:** "Can you explain REST APIs and also tell me about Hitler?"  
                    **Response:** "I can only provide information related to the lecture."  

                3. **General Lecture Questions:**  
                - If the user asks **general questions about the lecture** (e.g., "What is this lecture about?", "Summarize this lecture"),  
                    - DO NOT use the lecture segments.  
                    - Provide a high-level summary.  
                    - Set `'isSegmentsRequired'` to `false`.  

                4. **Greetings & Farewells:**  
                - If the user says "hi", "hello", "thanks", "bye", etc., respond naturally and **do not include references** or additional follow-ups.  
                - Example:  
                    - **User:** "Thanks!" → **Response:** "You're welcome!"  
                    - **User:** "Bye!" → **Response:** "Goodbye! Have a great day!"  

                5. **Reference Usage:**  
                - You **must provide exactly 3 references** using a web search **only** if:  
                    - The user asks about the lecture generally.  
                    - The user asks a query directly related to the lecture.  
                - **DO NOT embed references within the answer text.**  
                - **If no web search is needed (e.g., greetings, farewells, irrelevant queries), return an empty reference list.**

                ### **Response Format:**
                Return a JSON object with these properties:
                - **'answer'**: A concise, relevant response. No reference links or extra formatting inside.  
                - **'isSegmentsRequired'**: `true` if lecture segments were used, `false` otherwise.  
                - **'references'**: A list of URLs (empty if no web search was performed).  

                ---

                ### **Context for Answer:**
                - **Previous Conversation:**  
                {conversation_context}

                - **User's Question:**  
                "{query}"

                - **Relevant Lecture Segments:**  
                {context}

                Now generate a **strictly relevant and concise** response in the required format.
            """

            # Initialize messages for the API call
            messages = [{"role": "user", "content": prompt}]

            # Define tools only if web_search is enabled
            tools = []
            if web_search:
                tools.append({
                    "type": "web_search",
                    "function": {
                        "name": "web_search",
                        "parameters": {"query": query, "num_results": 3}
                    }
                })

            # Get GPT response with structured output
            response = self.client.responses.create(
                model="gpt-4o",
                input=messages,
                tools=tools,  # Only includes web search if enabled
                temperature=0.7,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "lecture_response",
                        "schema": schema ,
                        "strict": True
                    }
                }
            )

             # Parse the structured response using Pydantic
            parsed_response = LectureResponse.model_validate_json(response.output_text)

            # Ensure references is empty if web_search was not requested
            if not web_search:
                parsed_response.references = []
            if not parsed_response.isSegmentsRequired:
                segments = []

            return {
                "answer": parsed_response.answer,
                "segments": segments,  # No segment processing logic provided
                "references": parsed_response.references
            }

        except Exception as e:
            print(f"Error in search_and_explain: {e}")
            return {
                "answer": "An error occurred while processing the request.",
                "segments": [],
                "references": []
            }