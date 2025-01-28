from typing import Dict, Any

import httpx
from deepgram import (
    DeepgramClient,
)
from ..core.config import settings

class TranscriptionService:
    def __init__(self):
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)

    async def transcribe_audio(self, audio_path: str) -> dict[str, Any]:
        with open(audio_path, 'rb') as audio:
            source = {'buffer': audio, 'mimetype': 'audio/mp3'}
            response = self.dg_client.listen.rest.v("1").transcribe_file(
                source,
                {
                    'language': 'hi',
                    'smart_format': True,
                    'model': 'nova-2',
                    'punctuate': True,
                    'summarize': True,
                    'paragraphs': True,
                    'utterances': True,
                },
                timeout=httpx.Timeout(300.0, connect=10.0)
            )

            paragraphs_data = response['results']['channels'][0]['alternatives'][0]['paragraphs']['paragraphs']

            # Create a list of paragraphs and their sentences
            paragraphs_list = [
                {
                    "paragraph_start": paragraph["start"],
                    "paragraph_end": paragraph["end"],
                    "sentences": [
                        {
                            "text": sentence["text"],
                            "start": sentence["start"],
                            "end": sentence["end"]
                        }
                        for sentence in paragraph["sentences"]
                    ]
                }
                for paragraph in paragraphs_data
            ]


            return {
                'transcript':response['results']['channels'][0]['alternatives'][0]['transcript'],
                'summary':response['results']['channels'][0]['alternatives'][0]['summaries'][0],
                'paragraphs':paragraphs_list
            }