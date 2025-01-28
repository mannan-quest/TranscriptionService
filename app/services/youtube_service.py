from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List, Optional
from datetime import datetime, timedelta
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class YouTubeQuotaError(Exception):
    """Custom exception for YouTube quota exceeded errors"""
    pass


class YouTubeServiceError(Exception):
    """Custom exception for YouTube service errors"""
    pass


class QuotaManager:
    def __init__(self):
        self.daily_quota_limit = 10000  # Default YouTube API quota limit
        self.quota_reset_time = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
        self.quota_used = 0
        self.quota_costs = {
            'search': 100,  # Cost for search.list
            'videos': 1,  # Cost for videos.list
        }

    def can_make_request(self, operation: str) -> bool:
        """Check if there's enough quota for the operation"""
        if datetime.now() >= self.quota_reset_time:
            self.reset_quota()

        return (self.quota_used + self.quota_costs.get(operation, 0)) <= self.daily_quota_limit

    def record_usage(self, operation: str):
        """Record the quota usage for an operation"""
        self.quota_used += self.quota_costs.get(operation, 0)

    def reset_quota(self):
        """Reset quota at the start of a new day"""
        self.quota_used = 0
        self.quota_reset_time = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)


class YouTubeService:
    def __init__(self):
        try:
            self.youtube = build('youtube', 'v3', developerKey=settings.YOUTUBE_API_KEY)
            self.quota_manager = QuotaManager()
            self.cache = {}
            self.cache_ttl = timedelta(hours=1)
        except Exception as e:
            raise YouTubeServiceError(f"Failed to initialize YouTube service: {str(e)}")

    def _get_cache_key(self, operation: str, **params) -> str:
        """Generate a cache key from operation and parameters"""
        param_str = ','.join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{operation}:{param_str}"

    def _get_cached_result(self, cache_key: str) -> Optional[dict]:
        """Get cached result if it exists and is not expired"""
        if cache_key in self.cache:
            result, timestamp = self.cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return result
            del self.cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, result: dict):
        """Cache the result with current timestamp"""
        self.cache[cache_key] = (result, datetime.now())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(YouTubeServiceError),
        retry_error_cls=YouTubeServiceError
    )
    def get_related_videos(self, topic: str, max_results: int = 5) -> List[dict]:
        """
        Search YouTube for videos related to the given topic with quota management and caching.
        """
        try:
            # Check cache first
            cache_key = self._get_cache_key('search', topic=topic, max_results=max_results)
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Check quota before making request
            if not self.quota_manager.can_make_request('search'):
                raise YouTubeQuotaError("Daily YouTube API quota exceeded")

            sanitized_topic = self._sanitize_search_query(topic)
            search_response = self._execute_search(sanitized_topic, max_results)

            # Record quota usage
            self.quota_manager.record_usage('search')

            # Process results and cache them
            results = self._process_search_results(search_response)
            self._cache_result(cache_key, results)

            return results

        except HttpError as e:
            if e.resp.status == 403 and 'quotaExceeded' in str(e):
                raise YouTubeQuotaError("YouTube API quota exceeded")
            elif e.resp.status in [429, 500, 503]:
                raise YouTubeServiceError(f"YouTube API temporary error: {str(e)}")
            raise YouTubeServiceError(f"YouTube API error: {str(e)}")

        except Exception as e:
            raise YouTubeServiceError(f"Unexpected error: {str(e)}")

    def get_video_details(self, video_id: str) -> dict:
        """
        Get additional details for a video with quota management and caching.
        """
        try:
            # Check cache first
            cache_key = self._get_cache_key('videos', video_id=video_id)
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Check quota before making request
            if not self.quota_manager.can_make_request('videos'):
                return {}  # Return empty dict if no quota available for optional details

            video_response = self.youtube.videos().list(
                part='statistics',
                id=video_id,
                fields='items(statistics(viewCount,likeCount))'
            ).execute()

            # Record quota usage
            self.quota_manager.record_usage('videos')

            result = video_response.get('items', [{}])[0].get('statistics', {})
            self._cache_result(cache_key, result)
            return result

        except Exception as e:
            print(f"Error fetching video details: {str(e)}")
            return {}  # Return empty dict for non-critical errors

    def _sanitize_search_query(self, query: str) -> str:
        """Sanitize the search query to prevent injection and improve results."""
        sanitized = ''.join(char for char in query if char.isalnum() or char.isspace())
        return sanitized[:100]  # Limit query length

    def _execute_search(self, topic: str, max_results: int) -> dict:
        """Execute the YouTube search with proper parameters."""
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
        """Process and format the search results with error handling."""
        videos = []
        for item in search_response.get('items', []):
            try:
                video_info = {
                    'title': item['snippet']['title'],
                    'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    'description': self._truncate_description(item['snippet']['description']),
                    'thumbnail': item['snippet']['thumbnails']['medium']['url'],
                    'channel_name': item['snippet']['channelTitle'],
                    'published_at': item['snippet']['publishedAt'],
                    'viewCount': '0'  # Default value
                }

                # Only get additional details if we have quota available
                if self.quota_manager.can_make_request('videos'):
                    video_details = self.get_video_details(item['id']['videoId'])
                    video_info.update(video_details)

                videos.append(video_info)
            except KeyError as e:
                print(f"Error processing video item: {str(e)}")
                continue
        return videos

    def _truncate_description(self, description: str, max_length: int = 200) -> str:
        """Truncate the description to a reasonable length."""
        if len(description) <= max_length:
            return description
        return description[:max_length].rsplit(' ', 1)[0] + '...'