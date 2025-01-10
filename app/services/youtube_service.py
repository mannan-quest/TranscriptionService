from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings


class YouTubeServiceError(Exception):
    """Custom exception for YouTube service errors"""
    pass


class YouTubeService:
    def __init__(self):
        try:
            self.youtube = build('youtube', 'v3', developerKey=settings.YOUTUBE_API_KEY)
        except Exception as e:
            raise YouTubeServiceError(f"Failed to initialize YouTube service: {str(e)}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry_error_cls=YouTubeServiceError
    )
    def get_related_videos(self, topic: str, max_results: int = 5) -> List[dict]:
        """
        Search YouTube for videos related to the given topic with retry logic.
        """
        try:
            sanitized_topic = self._sanitize_search_query(topic)
            search_response = self._execute_search(sanitized_topic, max_results)
            return self._process_search_results(search_response)

        except HttpError as e:
            if e.resp.status in [429, 500, 503]:  # Rate limit or server errors
                raise YouTubeServiceError(f"YouTube API temporary error: {str(e)}")
            raise YouTubeServiceError(f"YouTube API error: {str(e)}")

        except Exception as e:
            raise YouTubeServiceError(f"Unexpected error: {str(e)}")

    def _sanitize_search_query(self, query: str) -> str:
        """
        Sanitize the search query to prevent injection and improve results.
        """
        sanitized = ''.join(char for char in query if char.isalnum() or char.isspace())
        return sanitized[:100]

    def _execute_search(self, topic: str, max_results: int) -> dict:
        """
        Execute the YouTube search with proper parameters (synchronously).
        """
        return self.youtube.search().list(
            q=topic,
            part='snippet',
            type='video',
            maxResults=max_results,
            relevanceLanguage='en',
            order='relevance',
            safeSearch='moderate',
            fields='items(id/videoId,snippet(title,description,channelTitle,publishedAt,thumbnails/medium))'
        ).execute()

    def _process_search_results(self, search_response: dict) -> List[dict]:
        """
        Process and format the search results (synchronously).
        """
        videos = []
        for item in search_response.get('items', []):
            try:
                video_info = {
                    'title': item['snippet']['title'],
                    'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    'description': self._truncate_description(item['snippet']['description']),
                    'thumbnail': item['snippet']['thumbnails']['medium']['url'],
                    'channel_name': item['snippet']['channelTitle'],
                    'published_at': item['snippet']['publishedAt']
                }
                # Get additional video details
                video_details = self.get_video_details(item['id']['videoId'])
                video_info.update(video_details)
                videos.append(video_info)
            except KeyError as e:
                print(f"Error processing video item: {str(e)}")
                continue
        return videos

    def _truncate_description(self, description: str, max_length: int = 200) -> str:
        """
        Truncate the description to a reasonable length.
        """
        if len(description) <= max_length:
            return description
        return description[:max_length].rsplit(' ', 1)[0] + '...'

    def get_video_details(self, video_id: str) -> dict:
        """
        Get additional details for a video (synchronously).
        """
        video_response = self.youtube.videos().list(
            part='statistics',
            id=video_id,
            fields='items(statistics(viewCount,likeCount,dislikeCount))'
        ).execute()
        return video_response.get('items', [{}])[0].get('statistics', {})
