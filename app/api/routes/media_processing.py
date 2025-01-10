import os
import asyncio
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from starlette.websockets import WebSocket
from supabase import create_client

from ...core.config import settings
from ...services.assistant import Assistant
from ...services.live_data_formating import LiveDataFormating, AnalyzeLiveMediaRequest
from ...services.media_converter import MediaConverter
from ...services.transcription_service import TranscriptionService
from ...services.translation_service import TranslationAnalysisService
from ...services.youtube_service import YouTubeService

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
async def analyze_media(lecture_id: int):
    try:
        # Initialize 'loading' and 'progress'
        supabase.table("lectures").update({
            "loading": True,
            "progress": 0.0  # Start at 0%
        }).eq("lecture_id", lecture_id).execute()

        # Return an immediate response
        asyncio.create_task(process_media(lecture_id))  # Run processing asynchronously
        return {"message": "Processing started", "lecture_id": lecture_id}

    except Exception as e:
        print(f"Error analyzing media: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_media(lecture_id: int):
    """Process the media and update 'progress' column as each step completes."""
    try:
        def update_progress(value: float):
            supabase.table("lectures") \
                .update({"progress": value}) \
                .eq("lecture_id", lecture_id) \
                .execute()

        # 1) Fetch the file path from the 'lectures' table
        lecture_data = supabase.table("lectures") \
            .select("recording") \
            .eq("lecture_id", lecture_id) \
            .execute()
        transcription_path = lecture_data.data[0]["recording"]
        file_name = transcription_path.split("/", 1)[1]

        # Initialize services
        media_converter = MediaConverter()
        transcription_service = TranscriptionService()
        translation_service = TranslationAnalysisService()
        youtube_service = YouTubeService()

        # 2) Download the file from Supabase storage
        transcription_file = await media_converter.fetch_file_from_supabase('recordings', file_name)
        update_progress(0.1)  # 10% done

        # 3) Convert to audio if it's an MP4
        if transcription_file.endswith('.mp4'):
            audio_path = await media_converter.convert_video_to_audio(transcription_file)
        else:
            audio_path = transcription_file
        update_progress(0.2)  # 20% done

        # 4) Transcribe
        hindi_transcription = await transcription_service.transcribe_audio(audio_path)
        paragraphs = hindi_transcription.get('paragraphs', [])
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
                "viewCount": resource["viewCount"],
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

        # 11) Mark done
        update_progress(1.0)  # 100% done
        print(f"Processing completed for lecture {lecture_id}")

    except Exception as e:
        # If something fails, update the DB accordingly
        supabase.table("lectures").update({
            "loading": False,
            "error": str(e),
            "progress": 0.0  # Reset or keep partial progress as you wish
        }).eq("lecture_id", lecture_id).execute()
        raise e
        print(f"Error processing lecture {lecture_id}: {e}")


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
