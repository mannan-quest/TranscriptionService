import json
from typing import List, Dict, Any

from openai import AsyncOpenAI
from ..core.config import settings
from pydantic import BaseModel


class TranslateResponse(BaseModel):
    translation: str
    summary: str
    topic: str
    description: str

    class Config:
        extra = "forbid"

class OverallAnalysisResponse(BaseModel):
    overall_topic: str
    overall_summary: str
    overall_description: str

    class Config:
        extra = "forbid"

class AnalysisResult(BaseModel):
    topics: List[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "type": "object",
            "properties": {
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
                "topics"
            ]
        }



class TranslationAnalysisService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def analyze_material_text(self, paragraphs: List[str]) -> Dict[str, Any]:
        """Analyze text extracted from a PDF file."""
        try:
            # Create a prompt for analysis
            prompt = f"""
            Analyze the following content extracted from a PDF document:
            
            {paragraphs}

            I want you to make notes of the content and provide a detailed analysis of the content.
            Make sure to include the following:
                1. An overall topic/title for this content
                2. A brief description of the content
                3. A comprehensive summary
                4. Break this content into logical segments based on topic changes or section breaks.
            
            Format your response as Markdown with correct headings.
            
            Ensure you split the content into logical segments based on topic changes or section breaks.
            DO NOT PROVIDE ME WITH ANYTHING ELSE.
            """
            # Use OpenAI to analyze the content
            response = await self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            print(f"Response: {response}")
            # Parse the response
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error analyzing PDF text: {e}")
            raise

    async def analyze_full_text(self, paragraphs: List[dict]) -> dict:
        chunks = self.chunk_paragraphs_by_time(paragraphs)
        chunk_results = []

        for chunk in chunks:
            result = await self.analyze_chunks(chunk["paragraphs"])
            chunk_results.append(result)

        # Since chunk_results contains AnalysisResult objects, we need to access their data correctly
        all_topics = []
        translations = []

        # Combine all chunk translations
        for chunk_result in chunk_results:
            # If chunk_result is a dictionary (direct from parse())
            if isinstance(chunk_result, dict):
                topics = chunk_result.get("topics", [])
            # If chunk_result is a Pydantic model
            else:
                topics = chunk_result.topics

            all_topics.extend(topics)
            translations.extend(topic["translation"] for topic in topics)

        complete_translation = " ".join(translations)

        # Create overall analysis
        overall_analysis = {
            "overall_topic": "Overall Topic",
            "overall_summary": "Overall Summary",
            "overall_description": "Overall Description",
            "complete_translation": complete_translation,
            "topics": chunk_results
        }

        overall_analysis_response = await self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            response_format=OverallAnalysisResponse,
            messages=[{"role": "user", "content": f""""
             You are give a English Transcript of a Video, you are supposed to provide an overall analysis of the video.
                Please do the following in JSON format:
                1. Provide an "overall_topic", "overall_summary", and "overall_description" for the entire text.
                Transcript:
                {complete_translation}
            """}]
        )


        overall_analysis_data = overall_analysis_response.choices[0].message.parsed
        print('overall_analysis_response:', overall_analysis_data)
        overall_analysis["overall_topic"] = overall_analysis_data.overall_topic
        overall_analysis["overall_summary"] = overall_analysis_data.overall_summary
        overall_analysis["overall_description"] = overall_analysis_data.overall_description

        return overall_analysis


    async def analyze_chunks(self, paragraphs: List[dict]) -> dict:
        prompt = f"""
        You are given a Hindi/English transcript with timestamps in brackets like [start-end].
        You have to translate the text to English and analyze it.
        Please do the following in JSON format:
        1. Provide an "overall_topic", "overall_summary", and "overall_description" for the entire text.
        2. You are provided with a list of topics/segments with their start and end times. You are to combine the segments and then analyze them. About making new segments you should keep below things in mind:
            - A segment should be at least 5-10 minutes or 300 to 600 seconds long ( IMPORTANT )
            - Translate the text within each segment to English.
            - A segment should be a complete thought or idea.
            - Segment should not be short, its very important to keep the segment long enough.
        3. For each topic/segment, return:
           - "topic" (short name of the topic)
           - "description" (a few lines describing the topic)
           - "summary" (a short summary in English)
           - "translation" (verbatim English translation of the text within that segment)
           - "start_time" (earliest start time for this chunk)
           - "end_time" (latest end time for this chunk)
        4. All Segments combined should be the complete translation of the entire text. and No TimeStamp or any paragraph should be skipped.
        5. For each topic/segment translation, consider the following:
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

        Transcript with timestamps:
        {paragraphs}
        """

        # (C) Send the prompt to OpenAI
        response = await self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # Adjust model name to whatever is valid in your environment
            response_format=AnalysisResult,  # Our Pydantic model
            messages=[{"role": "user", "content": prompt}]
        )
        # (D) The structured data from the model:
        parsed_data = response.choices[0].message.parsed

        # print(f"parsed_data: {parsed_data}")
        # Return as dictionary
        return parsed_data


    def chunk_paragraphs_by_time(self,paragraphs, chunk_size=1000.0):
        # Sort by start time
        paragraphs_sorted = sorted(paragraphs, key=lambda p: p["paragraph_start"])

        chunks = []
        current_chunk = []

        current_start = 0.0
        current_end = chunk_size

        idx = 0
        while idx < len(paragraphs_sorted):
            para = paragraphs_sorted[idx]

            # If the paragraph lies (at least partially) within the current segment
            if para["paragraph_start"] < current_end:
                current_chunk.append(para)
                idx += 1
            else:
                # We’ve reached a paragraph that falls outside current 10-min window
                # store the current chunk if not empty
                if current_chunk:
                    chunks.append({
                        "start_time": current_start,
                        "end_time": current_end,
                        "paragraphs": current_chunk
                    })

                # move to the next 10-min window
                current_start = current_end
                current_end += chunk_size
                current_chunk = []

        # handle any leftover paragraphs
        if current_chunk:
            chunks.append({
                "start_time": current_start,
                "end_time": current_end,
                "paragraphs": current_chunk
            })

        return chunks
