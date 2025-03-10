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
    
    def get_notes(self) -> List[Dict[str, Any]]:
        segments = self.supabase.table('segments').select(
            'id, segment_notes'
        ).eq('lecture_id', self.lecture_id).execute()
        return segments.data

    async def generate_quiz(self, difficulty: str) -> List[Dict[str, Any]]:
        segments = self.get_notes()

        # Combine all segments content
        whole_content = ' '.join(segment['segment_notes'] for segment in segments)
        
        if difficulty == "easy":
            difficulty = "1-3"
            questions = 10
        elif difficulty == "medium":
            difficulty = "4-6"
            questions = 10
        elif difficulty == "hard":
            difficulty = "7-10"
            questions = 15

        # Create the prompt for OpenAI
        prompt = f"""
            You are an expert educator tasked with creating a thoughtful and challenging quiz based on lecture notes. Your goal is to generate questions that test understanding of the material at the specified difficulty level, focusing on key concepts and ideas rather than specific phrasings or minor details from the transcript.

            Here is the lecture transcript you'll be working with:

            <lecture_transcript>
            {whole_content}
            </lecture_transcript>

            The difficulty level for this quiz is:
            <difficulty_level>
            {difficulty}
            </difficulty_level>

            The number of questions to generate is:
            <num_questions>
            {questions}
            </num_questions>

            Before generating the quiz, please analyze the lecture notes and plan your questions. Wrap your lecture analysis and quiz planning process inside <lecture_analysis_and_quiz_planning> tags:

            <lecture_analysis_and_quiz_planning>
            1. Analyze the lecture content:
            - List 5-7 key concepts or terms
            - For each concept, provide a relevant quote from the lecture notes
            - Note 3-5 important facts or statistics
            - Summarize 2-3 main ideas or arguments
            - Extract 3-5 key quotes that represent important points

            2. Plan questions:
            - For each key concept, brainstorm 2-3 potential question ideas
            - Classify each question idea according to Bloom's Taxonomy
            - Generate ideas for multiple-choice, fill-in-the-blank, and true/false questions
            - Ensure questions align with the specified difficulty level
            - For harder questions, focus on real-world applications of concepts
            - Evaluate the difficulty of each planned question on a scale of 1-10
            - Review the distribution across Bloom's Taxonomy levels

            3. Evaluate question relevance and importance:
            - For each planned question, assess its relevance to the key concepts and ideas
            - Ensure questions test understanding rather than recall of minor details
            - Remove or revise any questions that focus on trivial information or lecturer's guidelines
            - Prioritize questions that encourage critical thinking and application of concepts

            4. Consider question formats:
            - Multiple choice: Create 4 options, each 5-6 words long make sure the option which is the answer is similar in length to the other options such that the user cannot easily guess the answer
            - Brainstorm plausible but incorrect "distractor" options
            - Fill-in-the-blank: Include 4 possible options
            - True/False: Create unambiguous statements

            5. Prepare explanations:
            - Note key points from the lecture that support correct answers
            - Identify potential misconceptions for incorrect answers
            - Ensure explanations reinforce understanding of key concepts

            6. Final difficulty check:
            - Review the set of questions as a whole
            - Ensure the overall difficulty matches the specified level
            - Adjust individual questions if necessary
            - Confirm appropriate question type distribution
            - Verify distribution across Bloom's Taxonomy levels

            7. Map questions to lecture content:
            - Identify the specific part of the lecture each question relates to
            - Ensure balanced coverage of the lecture material
            - Write down the relevant quote or section for each question

            8. Evaluate question type distribution:
            - Count the number of each question type
            - Adjust distribution if necessary for variety and appropriate difficulty
            - Aim for a balanced mix of multiple-choice, fill-in-the-blank, and true/false questions

            </lecture_analysis_and_quiz_planning>

            After completing your analysis and planning, generate the quiz using the following format:

            <quiz>
            <question_1>
            Type: [Multiple Choice / Fill-in-the-Blank / True/False]
            Question: [Insert question text here]
            [For multiple choice and fill-in-the-blank:]
            A. [Option A]
            B. [Option B]
            C. [Option C]
            D. [Option D]
            [For true/false:]
            True or False: [Statement]
            [Options for True and False]
            True
            False
            Correct Answer: [Insert correct answer or True/False]
            Explanation: [Explain correct answer and why other options are incorrect, if applicable]
            </question_1>

            [Repeat for each question, incrementing the question number]
            </quiz>

            Example Questions
            1. Multiple Choice
            Question: What is the capital of France?
            A. London
            B. Paris
            C. Berlin
            D. Madrid
            Correct Answer: Paris
            Explanation: Paris is the capital of France.

            2. Fill-in-the-Blank
            Question: The formula for calculating the area of a rectangle is length x _______.
            A. width
            B. height
            C. perimeter
            D. diameter
            Correct Answer: width
            Explanation: The area of a rectangle is calculated by multiplying the length by the width.

            3. True/False
            Question: The Earth is flat.
            A. True
            B. False
            Correct Answer: False
            Explanation: The Earth is an oblate spheroid, not flat.

            Important guidelines:
            1. Ensure all questions are clear, unambiguous, and directly related to the key concepts and ideas from the lecture notes, rather than specific phrasings or minor details from the transcript.
            2. Maintain consistency with the chosen difficulty level throughout the quiz.
            3. For harder questions, focus on real-world applications of concepts rather than theoretical justifications.
            4. Vary question types and complexity as needed to match the difficulty level.
            5. Aim for a balanced coverage of the lecture material, focusing on the most important concepts and ideas.
            6. Avoid questions about trivial information or lecturer's guidelines that don't contribute to understanding the subject matter.
            7. Make sure to follow the examples given for each type of question in the output format.
            8. Make sure the answer and the answer in options is same or else all will fail :(
            Remember, the goal is to create a quiz that effectively tests the student's understanding of the key concepts and ideas presented in the lecture, encouraging critical thinking and application of knowledge.

        """

        # Make the API call
        completion =  self.client.beta.chat.completions.parse(
            model="o3-mini",  # Adjust model name to whatever is valid in your environment
            response_format=Quiz,
            # temperature=0.9,
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
