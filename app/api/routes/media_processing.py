import os
import PyPDF2
import asyncio
import aiofiles
from typing import List
from openai import OpenAI
from datetime import datetime
from pydantic import BaseModel
from supabase import create_client
from starlette.websockets import WebSocket
from fastapi import APIRouter, UploadFile, File, HTTPException

from ...core.config import settings
from ...services.assistant import Assistant
from ...services.notes_service import NotesGeneration
from ...services.media_converter import MediaConverter
from ...services.youtube_service import YouTubeService
from ...services.quiz_generation import QuizGeneration
from ...services.embedding_service import EmbeddingService
from ...services.transcription_service import TranscriptionService
from ...services.translation_service import LectureAnalysis, TranslationAnalysisService
from ...services.live_data_formating import LiveDataFormating, AnalyzeLiveMediaRequest
from ...services.lec_material_notes import extract_text_from_pdf, LectureMaterialNotes
from ...services.lecture_search_service import SearchRequest, LectureSearchService, SearchCourseRequest

router = APIRouter()
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@router.post("/analyze-live-media", response_model=dict)
async def analyze_live_media(request: AnalyzeLiveMediaRequest):
    try:
        # create a new lecture in the database
        lecture_response = supabase.table("lectures").insert({
            "name": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "course_id": request.course_id,
            "date": datetime.now().date().isoformat(),
            "loading": True,
            "progress": 0.0  # Start at 0%
        }).execute()

        response = await LiveDataFormating().format_data(request)

        print('response topics:', response.topics)

        # Update the lecture with the analysis results
        supabase.table("lectures").update({
            "summary": response.overall_summary,
            "loading": False,
            "topic": response.overall_topic,
            "description": response.overall_description,
        }).eq("lecture_id", lecture_response.data[0]['lecture_id']).execute()

        # Insert Segments
        for topic in response.topics:
            segment_response = supabase.table("segments").insert({
                "lecture_id": lecture_response.data[0]['lecture_id'],
                "segment_start": topic["start_time"],
                "segment_end": topic["end_time"],
                "content": topic["translation"],
                "topic": topic["topic"],
                "description": topic["description"]
            }).execute()

            # Get the segment_id from the response
            segment_id = segment_response.data[0]['id']

            # Get YouTube resources for this segment's topic
            youtube_resources = YouTubeService().get_related_videos(topic["topic"], max_results=2)

            # Insert YouTube resources for this segment
            for resource in youtube_resources:
                supabase.table("segment_resources").insert({
                    "segment_id": segment_id,
                    "title": resource["title"],
                    "url": resource["url"],
                    "description": resource["description"],
                    "thumbnail": resource["thumbnail"],
                    "channel_name": resource["channel_name"],
                    "published_at": resource["published_at"],
                    "viewCount": resource["viewCount"],
                }).execute()

        # Insert YouTube resources
        youtube_service = YouTubeService()
        youtube_resources = youtube_service.get_related_videos(response.overall_topic)
        for resource in youtube_resources:
            supabase.table("resources").insert({
                "lecture_id": lecture_response.data[0]['lecture_id'],
                "title": resource["title"],
                "url": resource["url"],
                "description": resource["description"],
                "thumbnail": resource["thumbnail"],
                "channel_name": resource["channel_name"],
                "published_at": resource["published_at"],
                "viewCount": resource["viewCount"],
            }).execute()

        # insert notes from sentences into respective segments
        for sentence in request.sentences:
            for note in sentence.notes:
                print(f"Processing note: {note.content} (Type: {note.type})")
                # Find the segment that contains this sentence
                segment = supabase.table("segments") \
                    .select("id") \
                    .eq("lecture_id", lecture_response.data[0]['lecture_id']) \
                    .gte("segment_start", sentence.startTime) \
                    .lte("segment_end", sentence.endTime) \
                    .execute()
                if not segment.data:
                    print(f"No segment found for sentence: {sentence.text}")
                    continue
                segment_id = segment.data[0]['id']
                # Insert the note
                supabase.table("notes").insert({
                    "segment_id": segment_id,
                    "type": note.type,
                    "content": note.content,
                }).execute()

        supabase.table('lectures').update({
            "progress": 1.0,
            "loading": False
        }).eq('lecture_id', lecture_response.data[0]['lecture_id']).execute()

        return {
            'lecture_id': lecture_response.data[0]['lecture_id'],
        }
    except Exception as e:
        # supabase.table('lectures').update({
        #     "progress": 0.0,
        #     "loading": False,
        #     "error": str(e)
        # }).eq('lecture_id', lecture_response.data[0]['lecture_id']).execute()
        print(f"Error processing transcription data: {e}")
        raise e
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/analyze-media", response_model=dict)
async def analyze_media(lecture_id: int, file: UploadFile = File(...)):
    try:
        if not file.filename.endswith(('.mp3', '.mp4', '.pdf')):
            raise HTTPException(
                status_code=400,
                detail="Invalid file format. Only MP3 and MP4 files are supported."
            )

        # Initialize 'loading' and 'progress'
        supabase.table("lectures").update({
            "loading": True,
            "progress": 0.0
        }).eq("lecture_id", lecture_id).execute()

        # Create temp directory if it doesn't exist
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)

        # Save the file with a unique name to avoid conflicts
        file_path = os.path.join(temp_dir, f"lecture_{file.filename}")

        # Actually save the file to disk
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await file.read()  # async read
            await out_file.write(content)  # async write

        print('Saved file to:', file_path)

        # Check if the file is a PDF
        if file_path.endswith('.pdf'):
            # Process the PDF file
            asyncio.create_task(process_content(lecture_id, file_path))
        else:
            # Process the audio/video file
            asyncio.create_task(process_recording(lecture_id, file_path))
        return {"message": "Processing started", "lecture_id": lecture_id}

    except Exception as e:
        print(f"Error analyzing media: {e}")
        # Clean up file if it exists
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))

async def process_content(lecture_id: int, file_path: str):
    """Process the textual content and update 'progress' column as each step completes."""
    try:
        def update_progress(value: float):
            supabase.table("lectures") \
                .update({"progress": value}) \
                .eq("lecture_id", lecture_id) \
                .execute()

        # Initialize services
        translation_service = TranslationAnalysisService()
        youtube_service = YouTubeService()
        update_progress(0.2)  # 20% done

        # 1) Grab all the content from the file assuming it's a PDF
        if file_path.endswith('.pdf'):
            text_content = extract_text_from_pdf(file_path)   
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Only PDF files are supported.")
        update_progress(0.4)  # 40% done

        # 2) Get overall analysis
        analysis = await translation_service.analyze_lecture_text(text_content)
        print('analysis:', analysis)
        update_progress(0.6)  # 60% done

        # 3) Get YouTube resources
        youtube_resources = []
        for keyword in analysis.overall_keywords:
            print('keyword:', keyword)
            youtube_resources.extend(youtube_service.get_related_videos(keyword, max_results=1))
        update_progress(0.7)  # 70% done

        # 4) Clear old segments/resources
        segments_to_be_deleted = supabase.table("segments").select("id").eq("lecture_id", lecture_id).execute()
        for segment in segments_to_be_deleted.data:
            # Adjust to access `id` based on the structure
            supabase.table("segment_resources").delete().eq("segment_id", segment['id']).execute()
        supabase.table("segments").delete().eq("lecture_id", lecture_id).execute()
        supabase.table("resources").delete().eq("lecture_id", lecture_id).execute()
        
        # 5) Update main lecture data
        supabase.table("lectures").update({
            "summary": analysis.comprehensive_summary,
            "loading": False,
            "topic": analysis.overall_topic,
            "description": analysis.content_description,
        }).eq("lecture_id", lecture_id).execute()
        update_progress(0.8)  # 80% done

        # 6) Insert YouTube resources
        for resource in youtube_resources:
            supabase.table("resources").insert({
                "lecture_id": lecture_id,
                "title": resource["title"],
                "url": resource["url"],
                "description": resource["description"],
                "thumbnail": resource["thumbnail"],
                "channel_name": resource["channel_name"],
                "published_at": resource["published_at"],
            }).execute()
        update_progress(0.9)  # 90% done

        # 7) Insert Segments
        for segment in analysis.subtopics:
            segment_response = supabase.table("segments").insert({
                "lecture_id": lecture_id,
                "content": segment.original_content,
                "segment_start": 0,
                "segment_end": 0,
                "topic": segment.title,
                "description": segment.specific_summary ,
                "segment_notes": segment.detailed_description
            }).execute()

            # Get the segment_id from the response
            segment_id = segment_response.data[0]['id']

            # Get YouTube resources for this segment's topic
            segment_youtube_resources = []
            for keyword in segment.key_terminology:
                segment_youtube_resources.extend(youtube_service.get_related_videos(keyword, max_results=1))
            for resource in segment_youtube_resources:
                supabase.table("segment_resources").insert({
                    "segment_id": segment_id,
                    "title": resource["title"],
                    "url": resource["url"],
                    "description": resource["description"],
                    "thumbnail": resource["thumbnail"],
                    "channel_name": resource["channel_name"],
                    "published_at": resource["published_at"],
                    "viewCount": resource["viewCount"],
                }).execute()

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        vector_store = client.vector_stores.create(name=analysis.overall_topic + "_" + str(lecture_id))
        supabase.table("lectures").update({
            "vectorstore_id": vector_store.id,
        }).eq("lecture_id", lecture_id).execute()

        update_progress(1.0)  # 100% done

        await generate_embeddings(EmbeddingRequest(lecture_id=lecture_id))
        print(f"Processing completed for lecture {lecture_id}")

    except Exception as e:
        print(f"Error processing content: {e}")

async def process_recording(lecture_id: int, file_path: str):
    """Process the Recording and update 'progress' column as each step completes."""
    try:
        def update_progress(value: float):
            supabase.table("lectures") \
                .update({"progress": value}) \
                .eq("lecture_id", lecture_id) \
                .execute()

        # Initialize services
        media_converter = MediaConverter()
        transcription_service = TranscriptionService()
        translation_service = TranslationAnalysisService()
        youtube_service = YouTubeService()

        # 2) Download the file from Supabase storage
        # transcription_file = await media_converter.fetch_file_from_supabase('recordings', file_name)
        # update_progress(0.1)  # 10% done

        # 3) Convert to audio if it's an MP4
        # Convert to audio if it's an MP4

        audio_path = file_path
        update_progress(0.2)  # 20% done

        # 4) Transcribe
        hindi_transcription = await transcription_service.transcribe_audio(audio_path)
        paragraphs = hindi_transcription.get('paragraphs', [])
        print('paragraphs:', paragraphs)
        update_progress(0.4)  # 40% done

        # 5) Translate and analyze
        analysis = await translation_service.analyze_full_text(paragraphs)
        update_progress(0.6)  # 60% done

        # 6) Get YouTube resources
        youtube_resources = youtube_service.get_related_videos(analysis['overall_topic'])
        update_progress(0.7)  # 70% done

        # 7) Clear old segments/resources

        segments_to_be_deleted = supabase.table("segments").select("id").eq("lecture_id", lecture_id).execute()

        for segment in segments_to_be_deleted.data:
            # Adjust to access `id` based on the structure
            supabase.table("segment_resources").delete().eq("segment_id", segment['id']).execute()

        supabase.table("segments").delete().eq("lecture_id", lecture_id).execute()
        supabase.table("resources").delete().eq("lecture_id", lecture_id).execute()

        # 8) Update main lecture data
        supabase.table("lectures").update({
            "summary": analysis['overall_summary'],
            "loading": False,
            "topic": analysis["overall_topic"],
            "description": analysis["overall_description"],
        }).eq("lecture_id", lecture_id).execute()
        update_progress(0.8)  # 80% done

        # 9) Insert YouTube resources
        for resource in youtube_resources:
            supabase.table("resources").insert({
                "lecture_id": lecture_id,
                "title": resource["title"],
                "url": resource["url"],
                "description": resource["description"],
                "thumbnail": resource["thumbnail"],
                "channel_name": resource["channel_name"],
                "published_at": resource["published_at"],
            }).execute()
        update_progress(0.9)  # 90% done

        # 10) Insert Segments
        for paragraph in analysis["topics"]:
            for topic in paragraph.topics:
                # First insert the segment
                segment_response = supabase.table("segments").insert({
                    "lecture_id": lecture_id,
                    "segment_start": topic["start_time"],
                    "segment_end": topic["end_time"],
                    "content": topic["translation"],
                    "topic": topic["topic"],
                    "description": topic["description"]
                }).execute()

                print('segment_response:', segment_response)
                # Get the segment_id from the response
                segment_id = segment_response.data[0]['id']  # Assuming this is how Supabase returns the id

                # Get YouTube resources for this segment's topic
                segment_youtube_resources = youtube_service.get_related_videos(topic["topic"], max_results=2)

                # Insert YouTube resources for this segment
                for resource in segment_youtube_resources:
                    supabase.table("segment_resources").insert({
                        "segment_id": segment_id,
                        "title": resource["title"],
                        "url": resource["url"],
                        "description": resource["description"],
                        "thumbnail": resource["thumbnail"],
                        "channel_name": resource["channel_name"],
                        "published_at": resource["published_at"],
                        "viewCount": resource["viewCount"],
                    }).execute()

        # 11) Generate Notes 
        await generate_notes(lecture_id)
        
        # 12) Create a vector store on openai for this specific lecture
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        vector_store = client.vector_stores.create(name=resource["title"]+"_" + str(lecture_id))
        supabase.table("lectures").update({
            "vectorstore_id": vector_store.id,
        }).eq("lecture_id", lecture_id).execute()

        # 13) Mark done
        update_progress(1.0)  # 100% done
        await generate_embeddings(EmbeddingRequest(lecture_id=lecture_id))
        print(f"Processing completed for lecture {lecture_id}")

    except Exception as e:
        # If something fails, update the DB accordingly
        supabase.table("lectures").update({
            "loading": False,
            "error": str(e),
            "progress": 0.0  # Reset or keep partial progress as you wish
        }).eq("lecture_id", lecture_id).execute()
        print(f"Error processing lecture {lecture_id}: {e}")
        raise e
    finally:
        # Clean up temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

# Add this new endpoint
@router.post("/analyze-material", response_model=dict)
async def analyze_material(material_id: int , file: UploadFile = File(...)):
    try:
        # Initialize 'loading' and 'progress'
        supabase.table("lecture_materials").update({
            "progress": 0.0
        }).eq("material_id", material_id).execute()

        # Create temp directory if it doesn't exist
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)

        # Save the file with a unique name to avoid conflicts
        file_path = os.path.join(temp_dir, f"lecture_{file.filename}")

        # Actually save the file to disk
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await file.read()  # async read
            await out_file.write(content)  # async write
        
        file_type = file_path.split('.')[-1]
        print('file_type:', file_type)
        material_notes = LectureMaterialNotes(material_id, file_path, file_type)
        asyncio.create_task(material_notes.analyze_material())

        return {"message": "Processing started", "material_id": material_id}

    except Exception as e:
        print(f"Error analyzing media: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class EmbeddingRequest(BaseModel):
    lecture_id: int

@router.post('/generate_embeddings')
async def generate_embeddings(request: EmbeddingRequest):
    try:
        EmbeddingService().generate_embeddings(request.lecture_id)
        return {"message": "Embeddings generated successfully"}
    except Exception as e:
        print(f"Error generating embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/search_lectures')
async def search_lectures(request: SearchRequest):
    try:
        results = LectureSearchService().search_and_explain(request.query, request.lecture_id,request.conversation_history, request.vectorstore_id, request.top_k, request.web_search, request.file_search)
        return results
    except Exception as e:
        print(f"Error searching lectures: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CourseEmbeddingRequest(BaseModel):
    course_id: int

@router.post('/generate_course_embeddings')
async def generate_course_embeddings(request: CourseEmbeddingRequest):
    try:
        EmbeddingService().generate_course_embeddings(course_id=request.course_id)
        return {"message": "Course embeddings generated successfully"}
    except Exception as e:
        print(f"Error generating course embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/search_courses')
async def search_courses(request: SearchCourseRequest):
    try:
        embedding_service = LectureSearchService()
        results = embedding_service.search_and_explain_course(request.query, request.course_id,request.conversation_history, top_k=request.top_k)
        return results
    except Exception as e:
        print(f"Error searching courses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class QuizGenerationRequest(BaseModel):
    difficulty: str
    lecture_id: int

@router.post('/generate_quiz')
async def generate_quiz(request: QuizGenerationRequest) -> List[dict]:
    try:
        quiz = QuizGeneration(request.lecture_id)
        quiz_data = await quiz.generate_quiz(request.difficulty)
        return quiz_data
    except Exception as e:
        print(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

@router.post('/generate_notes')
async def generate_notes(lecture_id: int) -> List[dict]:
    try:
        notes = NotesGeneration(lecture_id)
        notes_data = await notes.generate_notes()
        # Update the notes in the database
        for notes in notes_data:
            print(f"Updating notes for segment {notes['segment_id']}...")
            supabase.table("segments").update({
                "segment_notes": notes["notes"]
            }).eq("id", notes["segment_id"]).execute()

        return notes_data
    except Exception as e:
        print(f"Error generating notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/generate_flashcards')
async def generate_flashcards(request: QuizGenerationRequest) -> List[dict]:
    try:
        quiz = QuizGeneration(request.lecture_id)
        flashcards = await quiz.generate_flashcards()
        return flashcards
    except Exception as e:
        print(f"Error generating flashcards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# For Live Transcription
@router.websocket('/listen')
async def websocket_listen(websocket: WebSocket):
    await websocket.accept()
    # Wait for authorization message
    try:
        print('Waiting for auth message')
        # auth_message = await websocket.receive_json()
        # print('auth_message:', auth_message)
        # if not auth_message or auth_message.get('type') != 'authorization':
        #     print('auth_message1:', auth_message)
        #     await websocket.close(code=4001, reason="Missing authorization")
        #     return

        # dg_api_key = auth_message.get('dg_api_key')
        # openai_api_key = auth_message.get('openai_api_key')
        dg_api_key = os.getenv('DEEPGRAM_API_KEY')
        openai_api_key = os.getenv('OPENAI_API_KEY')
        # if not verify_api_key(api_key):  # Implement your verification logic
        #     await websocket.close(code=4003, reason="Invalid API key")
        #     return

        query_params = websocket.query_params
        mode = query_params.get('mode', 'speed')

        assistant = Assistant(websocket, dg_api_key, openai_api_key, mode=mode)
        try:
            await asyncio.wait_for(assistant.run(), timeout=21600)
        except TimeoutError:
            print('Connection timeout')

    except Exception as e:
        print(f"Error in websocket_listen: {e}")
        await websocket.close(code=4002, reason="Authorization failed")
        return
