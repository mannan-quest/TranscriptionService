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
            print(f"Failed to initialize YouTube service: {str(e)}")
            # Continue without raising error - service will return empty results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry_error_cls=YouTubeServiceError
    )
    def get_related_videos(self, topic: str, max_results: int = 5) -> List[dict]:
        """
        Search YouTube for videos related to the given topic.
        Returns empty list if quota is exceeded or other errors occur.
        """
        try:
            sanitized_topic = self._sanitize_search_query(topic)
            search_response = self._execute_search(sanitized_topic, max_results)
            return self._process_search_results(search_response)
        except HttpError as e:
            if 'quotaExceeded' in str(e):
                print(f"YouTube API quota exceeded for topic: {topic}")
                return []
            elif e.resp.status in [429, 500, 503]:
                print(f"YouTube API temporary error: {str(e)}")
                return []
            print(f"YouTube API error: {str(e)}")
            return []
        except Exception as e:
            print(f"Unexpected error in YouTube service: {str(e)}")
            return []

    def _sanitize_search_query(self, query: str) -> str:
        """
        Sanitize the search query to prevent injection and improve results.
        """
        sanitized = ''.join(char for char in query if char.isalnum() or char.isspace())
        return sanitized[:100]

    def _execute_search(self, topic: str, max_results: int) -> dict:
        """
        Execute the YouTube search with proper parameters.
        """
        try:
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
        except Exception:
            return {'items': []}

    def _process_search_results(self, search_response: dict) -> List[dict]:
        """
        Process and format the search results.
        Returns empty list if any errors occur during processing.
        """
        videos = []
        try:
            for item in search_response.get('items', []):
                try:
                    video_info = {
                        'title': item['snippet']['title'],
                        'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                        'description': self._truncate_description(item['snippet']['description']),
                        'thumbnail': item['snippet']['thumbnails']['medium']['url'],
                        'channel_name': item['snippet']['channelTitle'],
                        'published_at': item['snippet']['publishedAt'],
                        'viewCount': '0'  # Default value if details can't be fetched
                    }

                    # Try to get additional details, but don't fail if we can't
                    try:
                        video_details = self.get_video_details(item['id']['videoId'])
                        video_info.update(video_details)
                    except:
                        pass

                    videos.append(video_info)
                except KeyError as e:
                    print(f"Error processing video item: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error processing search results: {str(e)}")
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
        Get additional details for a video.
        Returns empty dict if quota exceeded or other errors occur.
        """
        try:
            video_response = self.youtube.videos().list(
                part='statistics',
                id=video_id,
                fields='items(statistics(viewCount,likeCount))'
            ).execute()
            return video_response.get('items', [{}])[0].get('statistics', {})
        except Exception as e:
            print(f"Error fetching video details: {str(e)}")
            return {}