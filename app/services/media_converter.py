import os
from io import BytesIO

import moviepy as mp
from pathlib import Path
from fastapi import UploadFile
import aiofiles
from supabase import create_client
from ..core.config import settings
import magic


class MediaConverter:

    def __init__(self):
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)

    async def save_upload_file(self, upload_file: UploadFile) -> str:
        upload_folder = Path(settings.UPLOAD_FOLDER)
        upload_folder.mkdir(exist_ok=True)

        file_path = upload_folder / upload_file.filename
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await upload_file.read()
            await out_file.write(content)
        return str(file_path)

    async def convert_video_to_audio(self, video_path: str) -> str:
        video = mp.VideoFileClip(video_path)
        audio_path = video_path.rsplit(".", 1)[0] + ".mp3"
        video.audio.write_audiofile(audio_path)
        video.close()
        return audio_path

    async def fetch_file_from_supabase(self, bucket_name: str, file_path: str) -> str:
        """Downloads file from Supabase and saves locally with a fixed name."""
        try:

            response = self.supabase.storage.from_(bucket_name).download(file_path)

            mime_type = magic.from_buffer(response, mime=True)
            print(f"MIME type: {mime_type}")

            if isinstance(response, str):
                raise Exception(f"Failed to fetch file: {response}")

            local_file_path = f'temp_media_file.{mime_type.split("/")[1]}'

            with open(local_file_path, 'wb') as f:
                # response is already bytes
                f.write(response)

            return local_file_path

        except Exception as e:
            print(f"Error fetching file from Supabase: {e}")
            raise