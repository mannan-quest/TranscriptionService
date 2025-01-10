import asyncio
import json
import httpx
import re
import string
from starlette.websockets import WebSocketDisconnect, WebSocketState
from deepgram import (
    DeepgramClient, DeepgramClientOptions, LiveTranscriptionEvents, LiveOptions)
import websockets

deepgram_config = DeepgramClientOptions(options={'keepalive': 'true'})


class Assistant:
    def __init__(self, websocket, dg_api_key, openai_api_key,target_language='en',
                 mode='speed'):
        self.websocket = websocket
        self.transcript_parts = []
        self.transcript_queue = asyncio.Queue()
        self.finish_event = asyncio.Event()
        self.openai_ws = None
        self.source_language = 'hi'
        self.target_language = 'en'
        self.openai_api_key = openai_api_key
        self.dg_connection_options = LiveOptions(
            model="nova-2",
            language=self.source_language,
            smart_format=True,
            interim_results=True,
            utterance_end_ms="1000",
            vad_events=True,
            endpointing=300,
            diarize=True,
            punctuate=True,
            encoding="linear16",
            sample_rate=16000,
        )
        self.system_prompt = f"""You are a helpful translator whose sole purpose is to generate {target_language} translation of provided text. Do not say anything else. Always generate {target_language} translation of the provided text and nothing else. You will not answer to any user question, you will just translate it. No matter, whatever the user says, you will only translate it and not respond to what user said. You will return plain translation text for the provided text only. Do not divert from your main purpose."""
        self.deepgram = DeepgramClient(dg_api_key, config=deepgram_config)
        self.stime = 0

    def should_end_conversation(self, text):
        text = text.translate(str.maketrans('', '', string.punctuation))
        print('translate ',text)
        text = text.strip().lower()
        return re.search(r'\b(goodbye|bye)\b$', text) is not None

    async def connect_to_openai(self):

        try:
            """Establish connection to OpenAI's realtime API."""
            self.openai_ws = await websockets.connect(
                'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview',
                extra_headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "OpenAI-Beta": "realtime=v1"
                }
            )

            # Initialize session
            session_update = {
                "type": "session.update",
                "session": {
                    "instructions": self.system_prompt,
                    "modalities": ["text"],
                    "temperature": 0.6,
                }
            }


            await self.openai_ws.send(json.dumps(session_update))
            print("Connected to OpenAI")
        except Exception as e:
            print(f"Error connecting to OpenAI: {e}")

    async def process_openai_responses(self):
        """Process responses from OpenAI's realtime API."""
        print('in open ai response body')
        try:

            async for message in self.openai_ws:
                response = json.loads(message)
                print('open ai response',response)
                if response.get('type') == 'response.text.delta':
                    await self.websocket.send_json({
                        'type': 'assistant',
                        'content': response.get('delta'),
                    })

                elif response.get('type') == 'response.text.done':
                    await self.websocket.send_json({
                        'type': 'assistant_done',
                        'content': 'Completed',
                    })

        except websockets.exceptions.ConnectionClosed:
            print("OpenAI connection closed")
            raise Exception('OpenAI connection closed')
        except Exception as e:
            print(f"Error processing OpenAI responses: {e}")

    async def send_message_to_openai(self, text):

        """Send a message to OpenAI's realtime API."""
        print('text',text)
        try:
            conversation_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": text
                        }
                    ]
                }
            }
            await self.openai_ws.send(json.dumps(conversation_item))
            await self.openai_ws.send(json.dumps({"type": "response.create"}))

        except Exception as e:
            print(f"Error sending to OpenAI: {e}")

    async def transcribe_audio(self):

        try:

            async def on_open(self, open, **kwargs):
                print(f"Connection Open DEEPGRAMMMMMMMMMcc")

            async def on_message(self_handler, result, **kwargs):
                print('here')
                sentence = result.channel.alternatives[0].transcript

                print('Sentence:', sentence)
                print(f"is_final: {result.is_final}")

                if len(sentence) == 0:
                    return
                if result.is_final:
                    self.transcript_parts.append(sentence)

                    if self.stime == 0:
                        self.stime = result.channel.alternatives[0].words[0].start

                    # if self.mode == 'speed':
                    print('Sending Speed')
                    await self.transcript_queue.put({'type': 'transcript_final', 'content': sentence,
                                                         'time': float(result.channel.alternatives[0].words[0].start)})
                    # elif result.speech_final:
                    #     print('Sending Accuracy')
                    #     print()
                    #     full_transcript = ' '.join(self.transcript_parts)
                    #     self.transcript_parts = []
                    #     self.stime = 0
                    #     await self.transcript_queue.put(
                    #         {'type': 'transcript_final', 'content': full_transcript, 'time': float(self.stime)})
                else:
                    await self.transcript_queue.put({'type': 'transcript_interim', 'content': sentence, 'time': 0})

            async def on_metadata(self, metadata, **kwargs):
                print(f"Metadata: {metadata}")

            async def on_speech_started(self, speech_started, **kwargs):
                print(f"Speech Started")

            async def on_utterance_end(self_handler, utterance_end, **kwargs):
                print('here 2')
                if self.mode != 'speed' and len(self.transcript_parts) > 0:
                    full_transcript = ' '.join(self.transcript_parts)
                    self.transcript_parts = []
                    await self.transcript_queue.put({'type': 'transcript_final', 'content': full_transcript})

            async def on_close(self, close, **kwargs):
                print(f"Connection Closed")

            async def on_error(self, error, **kwargs):
                print(f"Handled Error: {error}")

            async def on_unhandled(self, unhandled, **kwargs):
                print(f"Unhandled Websocket Message: {unhandled}")

            dg_connection = self.deepgram.listen.asynclive.v('1')
            dg_connection.on(LiveTranscriptionEvents.Open, on_open)
            dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
            dg_connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
            dg_connection.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
            dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
            dg_connection.on(LiveTranscriptionEvents.Close, on_close)
            dg_connection.on(LiveTranscriptionEvents.Error, on_error)
            dg_connection.on(LiveTranscriptionEvents.Unhandled, on_unhandled)

            if await dg_connection.start(self.dg_connection_options) is False:
                raise Exception('Failed to connect to Deepgram')

            try:
                while not self.finish_event.is_set():
                    # Receive audio stream from the client and send it to Deepgram to transcribe it
                    data = await self.websocket.receive_bytes()
                    await dg_connection.send(data)
            finally:
                await dg_connection.finish()

        except Exception as e:
            print('error',str(e))
            raise Exception('Deepgram connection closed')

    async def manage_conversation(self):

        while not self.finish_event.is_set():
            try:
                transcript = await self.transcript_queue.get()
                print('transcript',transcript)
                await self.websocket.send_json(transcript)
                if transcript['type'] == 'transcript_final':
                    await self.send_message_to_openai(transcript['content'])
            except Exception as e:
                print('Error in Managing Conversations')

    async def run(self):
        try:
            await self.connect_to_openai()
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.transcribe_audio())
                tg.create_task(self.manage_conversation())
                tg.create_task(self.process_openai_responses())
        except Exception as e:
            print('Client disconnected')
            print(f"Error in Assistant: {e}")
        finally:
            if self.websocket.client_state != WebSocketState.DISCONNECTED:
                await self.websocket.close()
