"""
Unified Media Management
Handles all media tracking using the unified_media table
Replaces processed_media.py, overseerr.py media tracking, and show subscriptions
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from seerr.database import get_db
from seerr.unified_models import UnifiedMedia
from seerr.db_logger import log_info, log_success, log_error, log_warning
from seerr.enhanced_season_manager import EnhancedSeasonManager

def create_notification(type: str, title: str, message: str, media_id: Optional[int] = None, 
                        media_type: Optional[str] = None, media_title: Optional[str] = None,
                        old_status: Optional[str] = None, new_status: Optional[str] = None) -> bool:
    """
    Create a notification in the notification_history table
    
    Args:
        type (str): Notification type (success, error, warning, info)
        title (str): Notification title
        message (str): Notification message
        media_id (int, optional): Associated media ID
        media_type (str, optional): Associated media type
        media_title (str, optional): Associated media title
        old_status (str, optional): Previous status
        new_status (str, optional): New status
        
    Returns:
        bool: True if notification created successfully
    """
    try:
        db = get_db()
        
        # Generate unique ID for notification
        import uuid
        notification_id = str(uuid.uuid4())
        
        # Prepare details JSON with media information
        details = {}
        if media_id:
            details['media_id'] = media_id
        if media_type:
            details['media_type'] = media_type
        if media_title:
            details['media_title'] = media_title
        if old_status:
            details['old_status'] = old_status
        if new_status:
            details['new_status'] = new_status
        
        # Import text from sqlalchemy for raw SQL
        from sqlalchemy import text
        import json
        
        # Insert notification using raw SQL with text() wrapper
        query = text("""
            INSERT INTO notification_history 
            (id, type, title, message, details, successful, viewed, timestamp, created_at)
            VALUES (:id, :type, :title, :message, :details, :successful, FALSE, NOW(), NOW())
        """)
        
        # Determine if notification represents success
        successful = type == 'success'
        
        db.execute(query, {
            'id': notification_id,
            'type': type,
            'title': title,
            'message': message,
            'details': json.dumps(details) if details else None,
            'successful': successful
        })
        db.commit()
        
        log_info("Notification", f"Created {type} notification: {title}")
        return True
        
    except Exception as e:
        log_error("Notification", f"Failed to create notification: {e}")
        return False
    finally:
        if 'db' in locals():
            db.close()

def generate_seasons_processing_string(seasons_data: List[Dict[str, Any]]) -> str:
    """
    Generate a seasons processing string from seasons_data
    
    Args:
        seasons_data: List of season dictionaries from seasons_data JSON
        
    Returns:
        str: Comma-separated string of season numbers (e.g., "1,2,3,4,5" or "1-5")
    """
    if not seasons_data or not isinstance(seasons_data, list):
        return ""
    
    season_numbers = []
    for season in seasons_data:
        if isinstance(season, dict) and 'season_number' in season:
            season_num = season['season_number']
            if isinstance(season_num, (int, str)) and str(season_num).isdigit():
                season_numbers.append(int(season_num))
    
    # Sort and remove duplicates
    season_numbers = sorted(list(set(season_numbers)))
    
    if not season_numbers:
        return ""
    
    # Create ranges for consecutive seasons (e.g., "1-5" instead of "1,2,3,4,5")
    if len(season_numbers) > 2:
        ranges = []
        start = season_numbers[0]
        end = start
        
        for i in range(1, len(season_numbers)):
            if season_numbers[i] == season_numbers[i-1] + 1:
                end = season_numbers[i]
            else:
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = season_numbers[i]
                end = start
        
        # Add the last range
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")
        
        return ",".join(ranges)
    else:
        return ",".join(map(str, season_numbers))

def get_media_by_id(media_id: int) -> Optional[UnifiedMedia]:
    """
    Get media record by ID
    
    Args:
        media_id (int): Media ID
        
    Returns:
        Optional[UnifiedMedia]: Media record if found, None otherwise
    """
    try:
        db = get_db()
        
        media_record = db.query(UnifiedMedia).filter(
            UnifiedMedia.id == media_id
        ).first()
        
        return media_record
        
    except Exception as e:
        log_error("Database Error", f"Error getting media by ID: {e}")
        return None
    finally:
        if 'db' in locals():
            db.close()

def has_complete_critical_data(media: UnifiedMedia) -> bool:
    """
    Check if media has complete critical data (IDs, title, type, etc.)
    Only checks fields that are essential for processing without Trakt API calls
    
    Args:
        media (UnifiedMedia): Media record to check
        
    Returns:
        bool: True if media has all critical data, False otherwise
    """
    if not media:
        return False
    
    # Check essential identification fields
    critical_fields = [
        ('tmdb_id', media.tmdb_id),
        ('imdb_id', media.imdb_id),
        ('media_type', media.media_type),
        ('title', media.title),
    ]
    
    # Check if all critical fields are present
    for field_name, field_value in critical_fields:
        if not field_value:
            return False
    
    # For TV shows, check if we have season data or at least total_seasons
    if media.media_type == 'tv':
        if not media.seasons_data and not media.total_seasons:
            return False
    
    return True

def is_media_processed(tmdb_id: int, media_type: str, imdb_id: Optional[str] = None, trakt_id: Optional[str] = None, overseerr_request_id: Optional[int] = None) -> Tuple[bool, Optional[UnifiedMedia]]:
    """
    Check if media has already been processed using unique identifiers
    
    Args:
        tmdb_id (int): TMDB ID of the media
        media_type (str): Type of media (movie/tv)
        imdb_id (str, optional): IMDB ID of the media
        trakt_id (str, optional): Trakt ID of the media
        overseerr_request_id (int, optional): Overseerr request ID for additional check
        
    Returns:
        Tuple[bool, Optional[UnifiedMedia]]: (is_processed, unified_media_record)
    """
    try:
        db = get_db()
        
        # Check by unique identifiers (tmdb_id, imdb_id, trakt_id)
        query = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == media_type
        )
        
        # Add additional filters if provided
        if imdb_id:
            query = query.filter(UnifiedMedia.imdb_id == imdb_id)
        if trakt_id:
            query = query.filter(UnifiedMedia.trakt_id == trakt_id)
        if overseerr_request_id:
            query = query.filter(UnifiedMedia.overseerr_request_id == overseerr_request_id)
        
        processed_media = query.first()
        
        if processed_media:
            # Only consider it "processed" if the status is 'completed'
            # This prevents overwriting completed items
            is_completed = processed_media.status == 'completed'
            return is_completed, processed_media
        else:
            return False, None
            
    except Exception as e:
        log_error("Database Error", f"Error checking if media is processed: {e}")
        return False, None
    finally:
        if 'db' in locals():
            db.close()

def is_media_processing(tmdb_id: int, media_type: str) -> bool:
    """
    Check if media is currently being processed
    
    Args:
        tmdb_id (int): TMDB ID of the media
        media_type (str): Type of media (movie/tv)
        
    Returns:
        bool: True if media is currently being processed
    """
    try:
        db = get_db()
        
        processing_media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == media_type,
            UnifiedMedia.status == 'processing',
            UnifiedMedia.processing_stage != 're_queued_for_processing'
        ).first()
        
        return processing_media is not None
        
    except Exception as e:
        log_error("Database Error", f"Error checking if media is processing: {e}")
        return False
    finally:
        if 'db' in locals():
            db.close()

def fetch_and_cache_images_if_needed(tmdb_id: int, title: str, media_type: str, trakt_id: str, 
                                    existing_media: Optional[UnifiedMedia] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch and cache images from Trakt API if needed
    
    Args:
        tmdb_id (int): TMDB ID of the media
        title (str): Title of the media
        media_type (str): Type of media (movie/tv)
        trakt_id (str): Trakt ID of the media
        existing_media (UnifiedMedia, optional): Existing media record to check for image updates
        
    Returns:
        Optional[Dict[str, Any]]: Image data if fetched, None otherwise
    """
    if not trakt_id:
        return None
        
    try:
        from seerr.image_utils import store_media_images, should_update_image
        from seerr.db_logger import log_info, log_warning
        
        # Check if we need to update images (only for existing media)
        should_fetch_images = True
        if existing_media:
            # Check if images already exist and are recent
            if (existing_media.poster_image and existing_media.poster_image_size and 
                existing_media.updated_at):
                should_fetch_images = should_update_image(
                    existing_media.poster_image_size, 
                    existing_media.updated_at.isoformat(),
                    force_update=False
                )
        
        if should_fetch_images:
            log_info("Image Processing", f"Fetching images for {title} ({media_type}) from Trakt API...")
            image_data = store_media_images(title, tmdb_id, media_type, trakt_id)
            if image_data:
                log_info("Image Processing", f"Successfully cached images for {title}")
                return image_data
            else:
                log_warning("Image Processing", f"Failed to fetch images for {title}")
                return None
        else:
            log_info("Image Processing", f"Images for {title} are up to date, skipping fetch")
            return None
            
    except Exception as e:
        from seerr.db_logger import log_error
        log_error("Image Processing", f"Error fetching images for {title}: {e}")
        return None

def start_media_processing(tmdb_id: int, imdb_id: str, trakt_id: str, media_type: str, 
                          title: str, year: int, overseerr_request_id: Optional[int] = None,
                          overseerr_media_id: Optional[int] = None, processing_stage: str = 'browser_automation',
                          extra_data: Optional[Dict[str, Any]] = None, cache_images: bool = True,
                          image_data: Optional[Dict[str, Any]] = None, media_details: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """
    Start tracking media processing in the unified_media table
    
    Args:
        tmdb_id (int): TMDB ID of the media
        imdb_id (str): IMDB ID of the media
        trakt_id (str): Trakt ID of the media
        media_type (str): Type of media (movie/tv)
        title (str): Title of the media
        year (int): Year of the media
        overseerr_request_id (int, optional): Overseerr request ID
        overseerr_media_id (int, optional): Overseerr media ID
        processing_stage (str): Current processing stage
        extra_data (dict, optional): Additional data
        cache_images (bool): Whether to cache images
        image_data (dict, optional): Pre-fetched image data
        media_details (dict, optional): Rich metadata from Trakt API (overview, genres, runtime, rating, etc.)
        
    Returns:
        Optional[int]: ID of the created record, or None if failed
    """
    try:
        db = get_db()
        
        # Check if media already exists
        existing_media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == media_type
        ).first()
        
        # Fetch and cache images if requested and not already provided
        if cache_images and not image_data and trakt_id:
            fetched_image_data = fetch_and_cache_images_if_needed(tmdb_id, title, media_type, trakt_id, existing_media)
            if fetched_image_data:
                image_data = fetched_image_data
        
        if existing_media:
            # Update existing record - but preserve status if already completed or processing
            current_status = existing_media.status
            was_newly_created = False  # Track if this was just created (for notification)
            
            # Check if this is a very recent creation (within last 5 seconds) - might be from track_media_request
            time_since_creation = (datetime.utcnow() - existing_media.created_at).total_seconds() if existing_media.created_at else 999
            
            # Check released_date first to determine if media should be unreleased
            should_be_unreleased = False
            if media_details and media_details.get('released_date'):
                released_date = media_details.get('released_date')
                # Ensure released_date is timezone-aware for comparison
                if released_date.tzinfo is None:
                    released_date = released_date.replace(tzinfo=timezone.utc)
                
                current_time = datetime.now(timezone.utc)
                if released_date > current_time:
                    should_be_unreleased = True
            
            # Only update status to 'processing' if it's not already completed, processing, or unreleased
            # But check released_date first - if it's unreleased, keep it that way
            if should_be_unreleased and current_status not in ['processing', 'completed', 'failed']:
                existing_media.status = 'unreleased'
                existing_media.processing_stage = processing_stage
                log_info("Media Processing", f"Media {existing_media.title} is unreleased, preserving unreleased status")
            elif current_status not in ['completed', 'processing', 'unreleased']:
                existing_media.status = 'processing'
                existing_media.processing_stage = processing_stage
                existing_media.processing_started_at = datetime.utcnow()
                log_info("Media Processing", f"Updated status to 'processing' for {existing_media.title} (was: {current_status})")
            else:
                # Preserve existing status but update other fields
                existing_media.processing_stage = processing_stage
                if current_status == 'processing':
                    # Only update processing_started_at if it's not already set
                    if not existing_media.processing_started_at:
                        existing_media.processing_started_at = datetime.utcnow()
                log_info("Media Processing", f"Preserved status '{current_status}' for {existing_media.title}")
            
            existing_media.last_checked_at = datetime.utcnow()
            existing_media.extra_data = extra_data
            existing_media.updated_at = datetime.utcnow()
            
            # Set seasons_processing for TV shows
            if media_type == 'tv' and extra_data and 'requested_seasons' in extra_data:
                requested_seasons = extra_data['requested_seasons']
                if requested_seasons:
                    # Convert season numbers to string format
                    season_numbers = []
                    for season in requested_seasons:
                        if isinstance(season, str) and season.startswith('Season '):
                            season_num = season.split()[-1]
                            if season_num.isdigit():
                                season_numbers.append(int(season_num))
                        elif isinstance(season, (int, str)) and str(season).isdigit():
                            season_numbers.append(int(season))
                    
                    if season_numbers:
                        season_numbers = sorted(list(set(season_numbers)))
                        if len(season_numbers) > 2:
                            # Create ranges for consecutive seasons
                            ranges = []
                            start = season_numbers[0]
                            end = start
                            
                            for i in range(1, len(season_numbers)):
                                if season_numbers[i] == season_numbers[i-1] + 1:
                                    end = season_numbers[i]
                                else:
                                    if start == end:
                                        ranges.append(str(start))
                                    else:
                                        ranges.append(f"{start}-{end}")
                                    start = season_numbers[i]
                                    end = start
                            
                            # Add the last range
                            if start == end:
                                ranges.append(str(start))
                            else:
                                ranges.append(f"{start}-{end}")
                            
                            existing_media.seasons_processing = ",".join(ranges)
                        else:
                            existing_media.seasons_processing = ",".join(map(str, season_numbers))
            
            # Update image data if provided
            if image_data:
                if 'poster_url' in image_data:
                    existing_media.poster_url = image_data['poster_url']
                if 'poster_image' in image_data:
                    existing_media.poster_image = image_data['poster_image']
                if 'poster_image_format' in image_data:
                    existing_media.poster_image_format = image_data['poster_image_format']
                if 'poster_image_size' in image_data:
                    existing_media.poster_image_size = image_data['poster_image_size']
                if 'thumb_url' in image_data:
                    existing_media.thumb_url = image_data['thumb_url']
                if 'thumb_image' in image_data:
                    existing_media.thumb_image = image_data['thumb_image']
                if 'thumb_image_format' in image_data:
                    existing_media.thumb_image_format = image_data['thumb_image_format']
                if 'thumb_image_size' in image_data:
                    existing_media.thumb_image_size = image_data['thumb_image_size']
                if 'fanart_url' in image_data:
                    existing_media.fanart_url = image_data['fanart_url']
                if 'fanart_image' in image_data:
                    existing_media.fanart_image = image_data['fanart_image']
                if 'fanart_image_format' in image_data:
                    existing_media.fanart_image_format = image_data['fanart_image_format']
                if 'fanart_image_size' in image_data:
                    existing_media.fanart_image_size = image_data['fanart_image_size']
                if 'backdrop_url' in image_data:
                    existing_media.backdrop_url = image_data['backdrop_url']
                if 'backdrop_image' in image_data:
                    existing_media.backdrop_image = image_data['backdrop_image']
                if 'backdrop_image_format' in image_data:
                    existing_media.backdrop_image_format = image_data['backdrop_image_format']
                if 'backdrop_image_size' in image_data:
                    existing_media.backdrop_image_size = image_data['backdrop_image_size']
            
            # Update rich media data if available
            if media_details:
                released_date = media_details.get('released_date')
                if released_date:
                    # Ensure released_date is timezone-aware for comparison
                    if released_date.tzinfo is None:
                        released_date = released_date.replace(tzinfo=timezone.utc)
                    
                    existing_media.released_date = released_date
                    current_time = datetime.now(timezone.utc)
                    if released_date > current_time:
                        # Media is unreleased - set status to unreleased if not already processing/completed/failed
                        # (Status check was already done above, but this ensures released_date is stored)
                        if existing_media.status not in ['processing', 'completed', 'failed']:
                            existing_media.status = 'unreleased'
                            log_info("Media Processing", f"Media {existing_media.title} is unreleased (releases {released_date.strftime('%Y-%m-%d')}), status set to unreleased")
            
            db.commit()
            log_info("Media Processing", f"Updated existing media record for {title} (TMDB: {tmdb_id})")
            
            # Check if this is a new request being added (overseerr_request_id being set for first time)
            # This indicates a new request even if the media record already existed
            is_new_request = (overseerr_request_id and 
                            existing_media.overseerr_request_id is None and 
                            time_since_creation > 10)  # Not just created, so this is a new request for existing media
            
            # Only create "New Media Added" notification if this was just created (within last 2 seconds)
            # AND it doesn't already have an overseerr_request_id (meaning track_media_request hasn't run yet)
            # This prevents duplicate notifications when both functions run
            if time_since_creation < 2 and existing_media.overseerr_request_id is None:
                create_notification(
                    type='info',
                    title='New Media Added',
                    message=f"New {media_type.upper()} added: {title} ({year})",
                    media_id=existing_media.id,
                    media_type=media_type,
                    media_title=title,
                    old_status=None,
                    new_status=existing_media.status
                )
            elif is_new_request:
                # New request for existing media - notify as new request
                create_notification(
                    type='info',
                    title='New Media Request',
                    message=f"New {media_type.upper()} request: {title} ({year})",
                    media_id=existing_media.id,
                    media_type=media_type,
                    media_title=title,
                    old_status=current_status,
                    new_status=existing_media.status
                )
            
            return existing_media.id
        else:
            # Create new record
            # Prepare image data for new record
            image_kwargs = {}
            if image_data:
                if 'poster_url' in image_data:
                    image_kwargs['poster_url'] = image_data['poster_url']
                if 'poster_image' in image_data:
                    image_kwargs['poster_image'] = image_data['poster_image']
                if 'poster_image_format' in image_data:
                    image_kwargs['poster_image_format'] = image_data['poster_image_format']
                if 'poster_image_size' in image_data:
                    image_kwargs['poster_image_size'] = image_data['poster_image_size']
                if 'thumb_url' in image_data:
                    image_kwargs['thumb_url'] = image_data['thumb_url']
                if 'thumb_image' in image_data:
                    image_kwargs['thumb_image'] = image_data['thumb_image']
                if 'thumb_image_format' in image_data:
                    image_kwargs['thumb_image_format'] = image_data['thumb_image_format']
                if 'thumb_image_size' in image_data:
                    image_kwargs['thumb_image_size'] = image_data['thumb_image_size']
                if 'fanart_url' in image_data:
                    image_kwargs['fanart_url'] = image_data['fanart_url']
                if 'fanart_image' in image_data:
                    image_kwargs['fanart_image'] = image_data['fanart_image']
                if 'fanart_image_format' in image_data:
                    image_kwargs['fanart_image_format'] = image_data['fanart_image_format']
                if 'fanart_image_size' in image_data:
                    image_kwargs['fanart_image_size'] = image_data['fanart_image_size']
                if 'backdrop_url' in image_data:
                    image_kwargs['backdrop_url'] = image_data['backdrop_url']
                if 'backdrop_image' in image_data:
                    image_kwargs['backdrop_image'] = image_data['backdrop_image']
                if 'backdrop_image_format' in image_data:
                    image_kwargs['backdrop_image_format'] = image_data['backdrop_image_format']
                if 'backdrop_image_size' in image_data:
                    image_kwargs['backdrop_image_size'] = image_data['backdrop_image_size']

            # Set seasons_processing for TV shows
            seasons_processing = None
            if media_type == 'tv' and extra_data and 'requested_seasons' in extra_data:
                requested_seasons = extra_data['requested_seasons']
                if requested_seasons:
                    # Convert season numbers to string format
                    season_numbers = []
                    for season in requested_seasons:
                        if isinstance(season, str) and season.startswith('Season '):
                            season_num = season.split()[-1]
                            if season_num.isdigit():
                                season_numbers.append(int(season_num))
                        elif isinstance(season, (int, str)) and str(season).isdigit():
                            season_numbers.append(int(season))
                    
                    if season_numbers:
                        season_numbers = sorted(list(set(season_numbers)))
                        if len(season_numbers) > 2:
                            # Create ranges for consecutive seasons
                            ranges = []
                            start = season_numbers[0]
                            end = start
                            
                            for i in range(1, len(season_numbers)):
                                if season_numbers[i] == season_numbers[i-1] + 1:
                                    end = season_numbers[i]
                                else:
                                    if start == end:
                                        ranges.append(str(start))
                                    else:
                                        ranges.append(f"{start}-{end}")
                                    start = season_numbers[i]
                                    end = start
                            
                            # Add the last range
                            if start == end:
                                ranges.append(str(start))
                            else:
                                ranges.append(f"{start}-{end}")
                            
                            seasons_processing = ",".join(ranges)
                        else:
                            seasons_processing = ",".join(map(str, season_numbers))

            # Prepare metadata fields from media_details
            metadata_kwargs = {}
            if media_details:
                if 'overview' in media_details:
                    metadata_kwargs['overview'] = media_details['overview']
                if 'genres' in media_details:
                    metadata_kwargs['genres'] = media_details['genres']
                if 'runtime' in media_details:
                    metadata_kwargs['runtime'] = media_details['runtime']
                if 'rating' in media_details:
                    metadata_kwargs['rating'] = media_details['rating']
                if 'vote_count' in media_details:
                    metadata_kwargs['vote_count'] = media_details['vote_count']
                if 'popularity' in media_details:
                    metadata_kwargs['popularity'] = media_details['popularity']
                # Add image URLs if not already in image_kwargs
                if 'poster_url' in media_details and 'poster_url' not in image_kwargs:
                    metadata_kwargs['poster_url'] = media_details['poster_url']
                if 'fanart_url' in media_details and 'fanart_url' not in image_kwargs:
                    metadata_kwargs['fanart_url'] = media_details['fanart_url']
                if 'backdrop_url' in media_details and 'backdrop_url' not in image_kwargs:
                    metadata_kwargs['backdrop_url'] = media_details['backdrop_url']
            
            # Determine initial status based on released_date
            initial_status = 'processing'
            if media_details and media_details.get('released_date'):
                released_date = media_details['released_date']
                # Ensure released_date is timezone-aware for comparison
                if released_date.tzinfo is None:
                    released_date = released_date.replace(tzinfo=timezone.utc)
                
                current_time = datetime.now(timezone.utc)
                if released_date > current_time:
                    initial_status = 'unreleased'
                    log_info("Media Processing", f"Media {title} is unreleased (releases {released_date.strftime('%Y-%m-%d')}), status set to unreleased")
                metadata_kwargs['released_date'] = released_date

            new_media = UnifiedMedia(
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                trakt_id=trakt_id,
                media_type=media_type,
                title=title,
                year=year,
                overseerr_request_id=overseerr_request_id,
                overseerr_media_id=overseerr_media_id,
                status=initial_status,
                processing_stage=processing_stage,
                processing_started_at=datetime.utcnow() if initial_status == 'processing' else None,
                last_checked_at=datetime.utcnow(),
                extra_data=extra_data,
                seasons_processing=seasons_processing,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                **image_kwargs,
                **metadata_kwargs
            )
            
            db.add(new_media)
            db.commit()
            
            log_info("Media Processing", f"Started tracking media processing for {title} (TMDB: {tmdb_id})")
            
            # Create notification for new media item
            create_notification(
                type='info',
                title='New Media Added',
                message=f"New {media_type.upper()} added: {title} ({year})",
                media_id=new_media.id,
                media_type=media_type,
                media_title=title,
                old_status=None,
                new_status=initial_status
            )
            
            return new_media.id
            
    except Exception as e:
        log_error("Database Error", f"Error starting media processing: {e}")
        if 'db' in locals():
            db.rollback()
        return None
    finally:
        if 'db' in locals():
            db.close()

def update_media_details(media_id: int, **kwargs) -> bool:
    """
    Update media details in the unified_media table
    
    Args:
        media_id (int): ID of the media record to update
        **kwargs: Any fields to update (title, overview, genres, etc.)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(UnifiedMedia.id == media_id).first()
        if not media:
            log_error("Database Error", f"Media record with ID {media_id} not found")
            return False
        
        # Update fields that exist in the model
        for field, value in kwargs.items():
            if hasattr(media, field):
                setattr(media, field, value)
        
        # Only update updated_at if the item is not currently being processed
        if media.status != 'processing':
            media.updated_at = datetime.utcnow()
        
        db.commit()
        
        log_success("Media Update", f"Updated media record {media_id} with new details")
        return True
        
    except Exception as e:
        log_error("Database Error", f"Error updating media details: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def update_media_processing_status(media_id: int, status: str, processing_stage: str = None, 
                                 error_message: str = None, extra_data: Optional[Dict[str, Any]] = None) -> bool:
    """
    Update the processing status of media
    
    Args:
        media_id (int): ID of the media record
        status (str): New status (pending, processing, completed, failed, skipped)
        processing_stage (str, optional): Current processing stage
        error_message (str, optional): Error message if failed
        extra_data (dict, optional): Additional data
        
    Returns:
        bool: True if update successful
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(UnifiedMedia.id == media_id).first()
        if not media:
            log_error("Media Update", f"Media record with ID {media_id} not found")
            return False
        
        # Capture old status for notification
        old_status = media.status
        
        media.status = status
        media.last_checked_at = datetime.utcnow()
        media.updated_at = datetime.utcnow()
        
        if processing_stage:
            media.processing_stage = processing_stage
        
        if error_message:
            media.error_message = error_message
            media.error_count = (media.error_count or 0) + 1
            media.last_error_at = datetime.utcnow()
        
        if extra_data:
            media.extra_data = extra_data
        
        if status == 'completed':
            media.processing_completed_at = datetime.utcnow()
            # Note: is_in_queue flag is managed by queue processing logic, not here
            # Queue processing will clear the flag when item is removed from queue
        elif status == 'processing':
            media.processing_started_at = datetime.utcnow()
        elif status == 'failed':
            # Note: is_in_queue flag is managed by queue processing logic, not here
            # Queue processing will clear the flag when item is removed from queue
            pass
        
        db.commit()
        
        log_info("Media Update", f"Updated media {media.title} (ID: {media_id}) status to {status}")
        
        # Create notification for status changes (but skip if going from None/None to a status - that's initial creation)
        if old_status != status and old_status is not None:
            # Determine notification type and message based on status
            if status == 'completed':
                notif_type = 'success'
                notif_title = 'Media Completed'
                notif_message = f"{media.title} has been successfully processed"
            elif status == 'failed':
                notif_type = 'error'
                notif_title = 'Media Failed'
                notif_message = f"{media.title} failed to process"
                if error_message:
                    notif_message += f": {error_message[:100]}"
            elif status == 'processing':
                # Only notify if coming from a different status (not from None/pending on initial creation)
                # But always notify if coming from 'failed' (retry scenario)
                if old_status in [None, 'pending']:
                    return True  # Skip notification for initial processing status (handled by "New Media Added")
                notif_type = 'info'
                notif_title = 'Media Processing Started'
                notif_message = f"{media.title} is now being processed"
            elif status == 'pending':
                # Don't notify for pending status (handled by "New Media Added")
                return True
            elif status == 'skipped':
                notif_type = 'warning'
                notif_title = 'Media Skipped'
                notif_message = f"{media.title} was skipped"
            elif status == 'unreleased':
                notif_type = 'info'
                notif_title = 'Media Unreleased'
                notif_message = f"{media.title} is not yet released"
            else:
                notif_type = 'info'
                notif_title = f'Media Status Changed'
                notif_message = f"{media.title} status changed from {old_status} to {status}"
            
            # Create notification
            create_notification(
                type=notif_type,
                title=notif_title,
                message=notif_message,
                media_id=media_id,
                media_type=media.media_type,
                media_title=media.title,
                old_status=old_status,
                new_status=status
            )
        
        return True
        
    except Exception as e:
        log_error("Database Error", f"Error updating media processing status: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def mark_episodes_complete(media_id: int, season_number: int = None, episode_numbers: List[int] = None, 
                          check_seerr: bool = True) -> Dict[str, Any]:
    """
    Mark episodes or entire season as complete for a TV show.
    
    Args:
        media_id (int): ID of the media record
        season_number (int, optional): Season number to mark. If None, marks entire show.
        episode_numbers (List[int], optional): Specific episode numbers to mark (e.g., [9, 10]).
                                              If None and season_number provided, marks all failed/unprocessed in that season.
        check_seerr (bool): Whether to check and mark as available in Seerr
        
    Returns:
        Dict with success status, message, and details about what was marked
    """
    try:
        from seerr.overseerr import check_media_availability, mark_completed
        from seerr.database import get_db
        
        db = get_db()
        try:
            media = db.query(UnifiedMedia).filter(UnifiedMedia.id == media_id).first()
            if not media:
                return {"success": False, "message": "Media record not found"}
            
            if media.media_type != 'tv':
                return {"success": False, "message": "This function only works for TV shows"}
            
            # Check Seerr availability if requested
            if check_seerr:
                availability = check_media_availability(media.tmdb_id, media.media_type)
                if availability and availability.get('available'):
                    seerr_media_id = availability.get('media_id')
                    if seerr_media_id:
                        mark_completed(seerr_media_id, media.tmdb_id)
            
            # Get or initialize seasons_data
            seasons_data = media.seasons_data or []
            if not seasons_data:
                log_warning("Episode Marking", f"No seasons_data found for {media.title}, cannot mark episodes", 
                           module="unified_media_manager", function="mark_episodes_complete")
                return {"success": False, "message": "No season data available for this show"}
            
            marked_episodes = []
            updated_seasons = []
            all_seasons_complete = True
            
            # Process each season
            for season_data in seasons_data:
                season_num = season_data.get('season_number')
                
                # If season_number specified, only process that season
                if season_number is not None and season_num != season_number:
                    updated_seasons.append(season_data)
                    # Check if this season is complete
                    confirmed = set(season_data.get('confirmed_episodes', []))
                    aired = season_data.get('aired_episodes', 0)
                    if len(confirmed) < aired:
                        all_seasons_complete = False
                    continue
                
                # Get current episode lists
                confirmed_episodes = set(season_data.get('confirmed_episodes', []))
                failed_episodes = set(season_data.get('failed_episodes', []))
                unprocessed_episodes = set(season_data.get('unprocessed_episodes', []))
                aired_episodes = season_data.get('aired_episodes', 0)
                
                # Determine which episodes to mark
                episodes_to_mark = set()
                
                if episode_numbers:
                    # Mark specific episodes
                    for ep_num in episode_numbers:
                        ep_id = f"E{str(ep_num).zfill(2)}"
                        episodes_to_mark.add(ep_id)
                elif season_number is not None:
                    # Mark all failed and unprocessed episodes in this season
                    episodes_to_mark = failed_episodes | unprocessed_episodes
                else:
                    # Mark entire show - all failed and unprocessed in all seasons
                    episodes_to_mark = failed_episodes | unprocessed_episodes
                
                # Update episode lists
                for ep_id in episodes_to_mark:
                    confirmed_episodes.add(ep_id)
                    failed_episodes.discard(ep_id)
                    unprocessed_episodes.discard(ep_id)
                    marked_episodes.append(f"Season {season_num} {ep_id}")
                
                # Update season data
                season_data['confirmed_episodes'] = sorted(list(confirmed_episodes))
                season_data['failed_episodes'] = sorted(list(failed_episodes))
                season_data['unprocessed_episodes'] = sorted(list(unprocessed_episodes))
                season_data['updated_at'] = datetime.utcnow().isoformat()
                
                # Check if season is complete
                if len(confirmed_episodes) >= aired_episodes and aired_episodes > 0:
                    season_data['status'] = 'completed'
                    season_data['is_complete'] = True
                else:
                    season_data['status'] = 'in_progress'
                    season_data['is_complete'] = False
                    all_seasons_complete = False
                
                updated_seasons.append(season_data)
            
            # Update media record
            media.seasons_data = updated_seasons
            media.last_checked_at = datetime.utcnow()
            media.updated_at = datetime.utcnow()
            
            # If all seasons are complete, mark show as completed
            if all_seasons_complete:
                media.status = 'completed'
                media.processing_completed_at = datetime.utcnow()
                # Preserve subscription status - don't change is_subscribed
                log_info("Episode Marking", f"All seasons complete for {media.title}, marked show as completed", 
                        module="unified_media_manager", function="mark_episodes_complete")
            else:
                # Keep current status or set to processing if it was failed
                if media.status == 'failed':
                    media.status = 'processing'
            
            db.commit()
            
            # Build response message
            if episode_numbers:
                message = f"Marked {len(episode_numbers)} episode(s) as complete in Season {season_number}"
            elif season_number is not None:
                message = f"Marked all remaining episodes in Season {season_number} as complete"
            else:
                message = f"Marked all remaining episodes in all seasons as complete"
            
            if all_seasons_complete:
                message += " (all seasons now complete)"
            
            return {
                "success": True,
                "message": message,
                "marked_episodes": marked_episodes,
                "all_seasons_complete": all_seasons_complete,
                "media_id": media_id
            }
            
        finally:
            db.close()
            
    except Exception as e:
        log_error("Database Error", f"Error marking episodes as complete: {e}", 
                 module="unified_media_manager", function="mark_episodes_complete")
        if 'db' in locals():
            db.rollback()
        return {"success": False, "message": f"Error: {str(e)}"}

def get_media_by_tmdb(tmdb_id: int, media_type: str) -> Optional[UnifiedMedia]:
    """
    Get media record by TMDB ID and media type
    
    Args:
        tmdb_id (int): TMDB ID of the media
        media_type (str): Type of media (movie/tv)
        
    Returns:
        Optional[UnifiedMedia]: Media record or None
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == media_type
        ).first()
        
        return media
        
    except Exception as e:
        log_error("Database Error", f"Error getting media by TMDB ID: {e}")
        return None
    finally:
        if 'db' in locals():
            db.close()

def get_all_media(status: Optional[str] = None, media_type: Optional[str] = None, 
                 limit: int = 100, offset: int = 0) -> List[UnifiedMedia]:
    """
    Get all media records with optional filtering
    
    Args:
        status (str, optional): Filter by status
        media_type (str, optional): Filter by media type
        limit (int): Maximum number of records to return
        offset (int): Number of records to skip
        
    Returns:
        List[UnifiedMedia]: List of media records
    """
    try:
        db = get_db()
        
        query = db.query(UnifiedMedia)
        
        if status:
            query = query.filter(UnifiedMedia.status == status)
        
        if media_type:
            query = query.filter(UnifiedMedia.media_type == media_type)
        
        media_list = query.order_by(UnifiedMedia.updated_at.desc()).offset(offset).limit(limit).all()
        
        return media_list
        
    except Exception as e:
        log_error("Database Error", f"Error getting media list: {e}")
        return []
    finally:
        if 'db' in locals():
            db.close()

def get_tv_subscriptions() -> List[UnifiedMedia]:
    """
    Get all TV show subscriptions
    
    Returns:
        List[UnifiedMedia]: List of subscribed TV shows
    """
    try:
        db = get_db()
        
        subscriptions = db.query(UnifiedMedia).filter(
            UnifiedMedia.media_type == 'tv',
            UnifiedMedia.is_subscribed == True
        ).all()
        
        return subscriptions
        
    except Exception as e:
        log_error("Database Error", f"Error getting TV subscriptions: {e}")
        return []
    finally:
        if 'db' in locals():
            db.close()

def update_tv_subscription(tmdb_id: int, season_number: int, episode_count: int = 0, 
                          aired_episodes: int = 0, confirmed_episodes: List[str] = None,
                          failed_episodes: List[str] = None, unprocessed_episodes: List[str] = None,
                          is_active: bool = True) -> bool:
    """
    Update TV show subscription data
    
    Args:
        tmdb_id (int): TMDB ID of the TV show
        season_number (int): Season number
        episode_count (int): Total episode count
        aired_episodes (int): Number of aired episodes
        confirmed_episodes (list): List of confirmed episode IDs
        failed_episodes (list): List of failed episode IDs
        unprocessed_episodes (list): List of unprocessed episode IDs
        is_active (bool): Whether subscription is active
        
    Returns:
        bool: True if update successful
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == 'tv'
        ).first()
        
        if not media:
            log_error("TV Subscription", f"TV show with TMDB ID {tmdb_id} not found")
            return False
        
        media.season_number = season_number
        media.episode_count = episode_count
        media.aired_episodes = aired_episodes
        media.confirmed_episodes = confirmed_episodes or []
        media.failed_episodes = failed_episodes or []
        media.unprocessed_episodes = unprocessed_episodes or []
        media.is_subscribed = True
        media.subscription_active = is_active
        media.subscription_last_checked = datetime.utcnow()
        media.updated_at = datetime.utcnow()
        
        db.commit()
        
        log_info("TV Subscription", f"Updated subscription for {media.title} Season {season_number}")
        return True
        
    except Exception as e:
        log_error("Database Error", f"Error updating TV subscription: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def subscribe_to_existing_show(tmdb_id: int, mark_existing_completed: bool = True) -> Optional[int]:
    """
    Subscribe to a TV show that may already exist in the library.
    Creates a media record with all existing seasons marked as completed,
    and sets up subscription for future episodes.
    
    Args:
        tmdb_id (int): TMDB ID of the TV show
        mark_existing_completed (bool): If True, mark all existing seasons as completed
        
    Returns:
        Optional[int]: Media ID if successful, None if failed
    """
    try:
        from seerr.trakt import get_media_details_from_trakt, get_all_seasons_from_trakt
        from seerr.enhanced_season_manager import EnhancedSeasonManager
        from seerr.image_utils import store_media_images
        from datetime import datetime, timezone
        
        db = get_db()
        
        # Check if media already exists
        existing_media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == 'tv'
        ).first()
        
        if existing_media:
            # Update existing media to subscribed
            existing_media.is_subscribed = True
            existing_media.subscription_active = True
            existing_media.subscription_last_checked = datetime.utcnow()
            
            # If mark_existing_completed is True, mark all seasons as completed
            if mark_existing_completed and existing_media.seasons_data:
                seasons_data = existing_media.seasons_data
                for season in seasons_data:
                    if isinstance(season, dict):
                        season['status'] = 'completed'
                        season['updated_at'] = datetime.utcnow().isoformat()
                        # Mark all aired episodes as confirmed
                        aired_episodes = season.get('aired_episodes', 0)
                        if aired_episodes > 0:
                            season['confirmed_episodes'] = [
                                f"E{str(i).zfill(2)}" for i in range(1, aired_episodes + 1)
                            ]
                            season['unprocessed_episodes'] = []
                
                existing_media.seasons_data = seasons_data
                existing_media.status = 'completed'
            
            db.commit()
            log_info("TV Subscription", f"Updated existing subscription for {existing_media.title}")
            return existing_media.id
        
        # Fetch media details from Trakt
        media_details = get_media_details_from_trakt(str(tmdb_id), 'tv')
        if not media_details:
            log_error("TV Subscription", f"Failed to fetch media details for TMDB ID {tmdb_id}")
            return None
        
        trakt_id = media_details.get('trakt_id')
        if not trakt_id:
            log_error("TV Subscription", f"No Trakt ID found for TMDB ID {tmdb_id}")
            return None
        
        # Fetch all seasons from Trakt
        all_seasons = get_all_seasons_from_trakt(str(trakt_id))
        if not all_seasons:
            log_warning("TV Subscription", f"No seasons found for show {tmdb_id}, creating with empty seasons")
            all_seasons = []
        
        # Create seasons_data with all existing seasons marked as completed
        seasons_data = []
        for season_info in all_seasons:
            season_number = season_info.get('number', 0)
            if season_number == 0:  # Skip specials
                continue
            
            # Get episode count from season info
            episodes = season_info.get('episodes', [])
            episode_count = len(episodes)
            
            # Count aired episodes (episodes with air_date in the past or today)
            current_date = datetime.now(timezone.utc).date()
            aired_episodes = 0
            for episode in episodes:
                air_date = episode.get('first_aired')
                if air_date:
                    try:
                        if isinstance(air_date, str):
                            ep_date = datetime.fromisoformat(air_date.replace('Z', '+00:00')).date()
                        else:
                            ep_date = air_date.date() if hasattr(air_date, 'date') else current_date
                        if ep_date <= current_date:
                            aired_episodes += 1
                    except Exception:
                        aired_episodes += 1  # Assume aired if we can't parse date
            
            # Create season data with all aired episodes marked as confirmed
            confirmed_episodes = []
            if mark_existing_completed and aired_episodes > 0:
                confirmed_episodes = [f"E{str(i).zfill(2)}" for i in range(1, aired_episodes + 1)]
            
            season_data = EnhancedSeasonManager.create_enhanced_season_data(
                season_number=season_number,
                episode_count=episode_count,
                aired_episodes=aired_episodes,
                confirmed_episodes=confirmed_episodes,
                failed_episodes=[],
                unprocessed_episodes=[],
                is_discrepant=False
            )
            seasons_data.append(season_data)
        
        # Determine title and year
        title = media_details.get('title', 'Unknown Show')
        year = media_details.get('year', 0)
        
        # Create new media record
        new_media = UnifiedMedia(
            tmdb_id=tmdb_id,
            imdb_id=media_details.get('imdb_id', ''),
            trakt_id=str(trakt_id),
            media_type='tv',
            title=title,
            year=year,
            overview=media_details.get('overview', ''),
            status='completed' if mark_existing_completed else 'pending',
            processing_stage='subscription_created',
            processing_completed_at=datetime.utcnow() if mark_existing_completed else None,
            last_checked_at=datetime.utcnow(),
            is_subscribed=True,
            subscription_active=True,
            subscription_last_checked=datetime.utcnow(),
            seasons_data=seasons_data,
            total_seasons=len(seasons_data),
            genres=media_details.get('genres', []),
            runtime=media_details.get('runtime', 0),
            rating=media_details.get('rating', 0.0),
            vote_count=media_details.get('vote_count', 0),
            popularity=media_details.get('popularity', 0.0),
            poster_url=media_details.get('poster_url', ''),
            fanart_url=media_details.get('fanart_url', ''),
            backdrop_url=media_details.get('backdrop_url', ''),
            released_date=media_details.get('released_date'),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(new_media)
        db.commit()
        
        # Store images
        try:
            store_media_images(tmdb_id, 'tv', trakt_id)
        except Exception as e:
            log_warning("TV Subscription", f"Failed to store images for {title}: {e}")
        
        log_info("TV Subscription", f"Created subscription for {title} with {len(seasons_data)} seasons marked as completed")
        
        # Create notification
        create_notification(
            type='info',
            title='Show Subscribed',
            message=f"Subscribed to {title}. Monitoring for future episodes.",
            media_id=new_media.id,
            media_type='tv',
            media_title=title,
            old_status=None,
            new_status='completed'
        )
        
        return new_media.id
        
    except Exception as e:
        log_error("Database Error", f"Error subscribing to show: {e}")
        if 'db' in locals():
            db.rollback()
        return None
    finally:
        if 'db' in locals():
            db.close()

def refresh_media_from_trakt(media_id: int, force_image_refresh: bool = False) -> bool:
    """
    Refresh media metadata and images from Trakt API for existing media.
    Does not change status or re-queue the item.
    
    Args:
        media_id (int): ID of the media record to refresh
        force_image_refresh (bool): If True, refresh images even if they exist
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from seerr.trakt import get_media_details_from_trakt, get_detailed_media_info
        from seerr.image_utils import store_media_images
        
        db = get_db()
        
        # Get existing media record
        media = db.query(UnifiedMedia).filter(UnifiedMedia.id == media_id).first()
        if not media:
            log_error("Trakt Refresh", f"Media record with ID {media_id} not found")
            return False
        
        if not media.tmdb_id:
            log_error("Trakt Refresh", f"Media {media_id} has no TMDB ID, cannot refresh from Trakt")
            return False
        
        log_info("Trakt Refresh", f"Refreshing Trakt data for {media.title} (ID: {media_id})")
        
        # Fetch fresh metadata from Trakt
        media_details = get_media_details_from_trakt(str(media.tmdb_id), media.media_type)
        if not media_details:
            log_error("Trakt Refresh", f"Failed to fetch media details from Trakt for {media.title}")
            return False
        
        # Get Trakt ID (use existing if available, otherwise from fetched data)
        trakt_id = media.trakt_id or media_details.get('trakt_id')
        if not trakt_id:
            log_error("Trakt Refresh", f"No Trakt ID found for {media.title}")
            return False
        
        # Fetch detailed info if we have Trakt ID
        detailed_info = None
        if trakt_id:
            try:
                detailed_info = get_detailed_media_info(int(trakt_id), 'movie' if media.media_type == 'movie' else 'show')
            except Exception as e:
                log_warning("Trakt Refresh", f"Could not fetch detailed info: {e}, using basic details")
        
        # Prepare update data
        update_data = {}
        
        # Update basic metadata
        if media_details.get('title'):
            update_data['title'] = media_details['title']
        if media_details.get('year'):
            update_data['year'] = media_details['year']
        if media_details.get('overview'):
            update_data['overview'] = media_details['overview']
        if media_details.get('imdb_id'):
            update_data['imdb_id'] = media_details['imdb_id']
        if trakt_id:
            update_data['trakt_id'] = str(trakt_id)
        
        # Update detailed metadata if available
        if detailed_info:
            if detailed_info.get('genres'):
                update_data['genres'] = detailed_info['genres']
            if detailed_info.get('runtime'):
                update_data['runtime'] = detailed_info['runtime']
            if detailed_info.get('rating'):
                update_data['rating'] = float(detailed_info['rating'])
            if detailed_info.get('votes'):
                update_data['vote_count'] = detailed_info['votes']
            if detailed_info.get('popularity'):
                update_data['popularity'] = float(detailed_info['popularity'])
            if detailed_info.get('released_date'):
                update_data['released_date'] = detailed_info['released_date']
        
        # Fetch and update images
        if force_image_refresh or not media.poster_image:
            log_info("Trakt Refresh", f"Fetching images for {media.title} from Trakt...")
            try:
                image_data = store_media_images(
                    media_details.get('title', media.title),
                    media.tmdb_id,
                    media.media_type,
                    str(trakt_id)
                )
                
                if image_data:
                    # Update image fields
                    if 'poster_url' in image_data:
                        update_data['poster_url'] = image_data['poster_url']
                    if 'poster_image' in image_data:
                        update_data['poster_image'] = image_data['poster_image']
                    if 'poster_image_format' in image_data:
                        update_data['poster_image_format'] = image_data['poster_image_format']
                    if 'poster_image_size' in image_data:
                        update_data['poster_image_size'] = image_data['poster_image_size']
                    
                    if 'thumb_url' in image_data:
                        update_data['thumb_url'] = image_data['thumb_url']
                    if 'thumb_image' in image_data:
                        update_data['thumb_image'] = image_data['thumb_image']
                    if 'thumb_image_format' in image_data:
                        update_data['thumb_image_format'] = image_data['thumb_image_format']
                    if 'thumb_image_size' in image_data:
                        update_data['thumb_image_size'] = image_data['thumb_image_size']
                    
                    if 'fanart_url' in image_data:
                        update_data['fanart_url'] = image_data['fanart_url']
                    if 'fanart_image' in image_data:
                        update_data['fanart_image'] = image_data['fanart_image']
                    if 'fanart_image_format' in image_data:
                        update_data['fanart_image_format'] = image_data['fanart_image_format']
                    if 'fanart_image_size' in image_data:
                        update_data['fanart_image_size'] = image_data['fanart_image_size']
                    
                    if 'backdrop_url' in image_data:
                        update_data['backdrop_url'] = image_data['backdrop_url']
                    if 'backdrop_image' in image_data:
                        update_data['backdrop_image'] = image_data['backdrop_image']
                    if 'backdrop_image_format' in image_data:
                        update_data['backdrop_image_format'] = image_data['backdrop_image_format']
                    if 'backdrop_image_size' in image_data:
                        update_data['backdrop_image_size'] = image_data['backdrop_image_size']
                    
                    log_info("Trakt Refresh", f"Successfully updated images for {media.title}")
                else:
                    log_warning("Trakt Refresh", f"Failed to fetch images for {media.title}")
            except Exception as e:
                log_warning("Trakt Refresh", f"Error fetching images for {media.title}: {e}")
        
        # Apply updates
        if update_data:
            update_media_details(media_id, **update_data)
            log_success("Trakt Refresh", f"Successfully refreshed Trakt data for {media.title}")
            return True
        else:
            log_warning("Trakt Refresh", f"No updates to apply for {media.title}")
            return False
        
    except Exception as e:
        log_error("Trakt Refresh", f"Error refreshing media from Trakt: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def get_media_by_overseerr_request(overseerr_request_id: int) -> Optional[UnifiedMedia]:
    """
    Get media record by Overseerr request ID
    
    Args:
        overseerr_request_id (int): Overseerr request ID
        
    Returns:
        Optional[UnifiedMedia]: Media record or None
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(
            UnifiedMedia.overseerr_request_id == overseerr_request_id
        ).first()
        
        return media
        
    except Exception as e:
        log_error("Database Error", f"Error getting media by Overseerr request ID: {e}")
        return None
    finally:
        if 'db' in locals():
            db.close()

def track_media_request(overseerr_request_id: int, overseerr_media_id: int, tmdb_id: int, 
                       imdb_id: str = None, trakt_id: str = None, media_type: str = None,
                       title: str = None, year: int = None, requested_by: str = None,
                       extra_data: Dict[str, Any] = None) -> Optional[int]:
    """
    Track a media request from Overseerr
    
    Args:
        overseerr_request_id (int): Overseerr request ID
        overseerr_media_id (int): Overseerr media ID
        tmdb_id (int): TMDB ID of the media
        imdb_id (str, optional): IMDB ID of the media
        trakt_id (str, optional): Trakt ID of the media
        media_type (str, optional): Type of media (movie/tv)
        title (str, optional): Title of the media
        year (int, optional): Year of the media
        requested_by (str, optional): Username who requested
        extra_data (dict, optional): Additional data
        
    Returns:
        Optional[int]: ID of the created/updated record
    """
    try:
        db = get_db()
        
        # Check if media already exists
        existing_media = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == media_type
        ).first()
        
        if existing_media:
            # Update existing record with request data
            existing_media.overseerr_request_id = overseerr_request_id
            existing_media.overseerr_media_id = overseerr_media_id
            existing_media.requested_by = requested_by
            existing_media.requested_at = datetime.utcnow()
            existing_media.first_requested_at = existing_media.first_requested_at or datetime.utcnow()
            existing_media.last_requested_at = datetime.utcnow()
            existing_media.request_count = (existing_media.request_count or 0) + 1
            existing_media.extra_data = extra_data
            # Only update updated_at if the item is not currently being processed
            if existing_media.status != 'processing':
                existing_media.updated_at = datetime.utcnow()
                log_info("Media Request", f"Updated updated_at for {existing_media.title} (status: {existing_media.status})")
            else:
                log_info("Media Request", f"Skipped updated_at update for {existing_media.title} (status: {existing_media.status})")
            
            db.commit()
            log_info("Media Request", f"Updated existing media record for request {overseerr_request_id}")
            return existing_media.id
        else:
            # Create new record
            new_media = UnifiedMedia(
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                trakt_id=trakt_id,
                media_type=media_type,
                title=title,
                year=year,
                overseerr_request_id=overseerr_request_id,
                overseerr_media_id=overseerr_media_id,
                requested_by=requested_by,
                requested_at=datetime.utcnow(),
                first_requested_at=datetime.utcnow(),
                last_requested_at=datetime.utcnow(),
                request_count=1,
                status='pending',
                extra_data=extra_data,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_media)
            db.commit()
            
            log_info("Media Request", f"Created new media record for request {overseerr_request_id}")
            
            # Create notification for new media item
            create_notification(
                type='info',
                title='New Media Added',
                message=f"New {media_type.upper()} added: {title} ({year})",
                media_id=new_media.id,
                media_type=media_type,
                media_title=title,
                old_status=None,
                new_status='pending'
            )
            
            return new_media.id
            
    except Exception as e:
        log_error("Database Error", f"Error tracking media request: {e}")
        if 'db' in locals():
            db.rollback()
        return None
    finally:
        if 'db' in locals():
            db.close()

def update_media_request_status(overseerr_request_id: int, status: str, 
                               error_message: str = None, completed_at: str = None) -> bool:
    """
    Update the status of a media request
    
    Args:
        overseerr_request_id (int): Overseerr request ID
        status (str): New status
        error_message (str, optional): Error message if failed
        completed_at (str, optional): Completion timestamp
        
    Returns:
        bool: True if update successful
    """
    try:
        db = get_db()
        
        media = db.query(UnifiedMedia).filter(
            UnifiedMedia.overseerr_request_id == overseerr_request_id
        ).first()
        
        if not media:
            log_error("Media Request", f"Media request {overseerr_request_id} not found")
            return False
        
        media.status = status
        media.updated_at = datetime.utcnow()
        
        if error_message:
            media.error_message = error_message
            media.error_count = (media.error_count or 0) + 1
            media.last_error_at = datetime.utcnow()
        
        if completed_at:
            media.processing_completed_at = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
        
        db.commit()
        
        log_info("Media Request", f"Updated request {overseerr_request_id} status to {status}")
        return True
        
    except Exception as e:
        log_error("Database Error", f"Error updating media request status: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def get_tv_show_season_count(tmdb_id: int) -> int:
    """
    Get the total number of seasons for a TV show from the database
    
    Args:
        tmdb_id (int): TMDB ID of the TV show
        
    Returns:
        int: Total number of seasons found in database (0 if none found)
    """
    try:
        db = get_db()
        
        # Get the TV show record
        tv_show = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == 'tv'
        ).first()
        
        if not tv_show:
            return 0
        
        # Return total_seasons if available, otherwise count from seasons_data
        if tv_show.total_seasons:
            return tv_show.total_seasons
        
        # Fallback: count from seasons_data
        seasons_data = tv_show.seasons_data or []
        return len(seasons_data)
        
    except Exception as e:
        log_error("Database Error", f"Error getting season count for TMDB ID {tmdb_id}: {e}")
        return 0
    finally:
        if 'db' in locals():
            db.close()

def update_tv_show_seasons_enhanced(tmdb_id: int, seasons_data: List[Dict[str, Any]], title: str) -> bool:
    """
    Update TV show with enhanced multi-season data including discrepancy detection
    
    Args:
        tmdb_id (int): TMDB ID of the TV show
        seasons_data (List[Dict]): List of season data dictionaries
        title (str): Title of the TV show for logging
        
    Returns:
        bool: True if update was successful
    """
    try:
        return EnhancedSeasonManager.update_tv_show_seasons(tmdb_id, seasons_data, title)
    except Exception as e:
        log_error("Enhanced Season Update", f"Error updating seasons for {title} (TMDB ID: {tmdb_id}): {e}")
        return False

def update_tv_show_season_count(tmdb_id: int, requested_seasons: List[int], title: str) -> bool:
    """
    Update TV show season count in database by adding new seasons to the seasons_data JSON field
    This approach stores all seasons for a TV show in a single record with a JSON array
    
    Args:
        tmdb_id (int): TMDB ID of the TV show
        requested_seasons (List[int]): List of season numbers requested from Overseerr
        title (str): Title of the TV show for logging
        
    Returns:
        bool: True if update was successful or no update needed
    """
    try:
        db = get_db()
        
        # Get the TV show record
        tv_show = db.query(UnifiedMedia).filter(
            UnifiedMedia.tmdb_id == tmdb_id,
            UnifiedMedia.media_type == 'tv'
        ).first()
        
        if not tv_show:
            log_warning("Season Count Update", f"No TV show record found for {title} (TMDB ID: {tmdb_id})")
            return False
        
        # Get current seasons data
        current_seasons_data = tv_show.seasons_data or []
        current_season_numbers = {season.get('season_number', 0) for season in current_seasons_data}
        
        # Find new seasons that need to be added
        new_seasons = [season for season in requested_seasons if season not in current_season_numbers]
        
        if not new_seasons:
            log_info("Season Count Update", f"No new seasons to add for {title} (current seasons: {sorted(current_season_numbers)})")
            return True
        
        # Add new seasons to the seasons_data JSON array
        for season_num in new_seasons:
            new_season_data = {
                'season_number': season_num,
                'episode_count': 0,
                'aired_episodes': 0,
                'confirmed_episodes': [],
                'failed_episodes': [],
                'unprocessed_episodes': [],
                'last_checked': None,
                'updated_at': datetime.utcnow().isoformat()
            }
            current_seasons_data.append(new_season_data)
            log_info("Season Count Update", f"Added Season {season_num} for {title}")
        
        # Sort seasons by season number
        current_seasons_data.sort(key=lambda x: x.get('season_number', 0))
        
        # Update the record
        tv_show.seasons_data = current_seasons_data
        tv_show.total_seasons = len(current_seasons_data)
        tv_show.seasons_processing = generate_seasons_processing_string(current_seasons_data)
        tv_show.updated_at = datetime.utcnow()
        
        db.commit()
        
        log_success("Season Count Update", f"Successfully added {len(new_seasons)} new seasons for {title} (seasons: {new_seasons})")
        return True
        
    except Exception as e:
        log_error("Database Error", f"Error updating season count for {title} (TMDB ID: {tmdb_id}): {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'db' in locals():
            db.close()

def update_tv_show_season_count_comprehensive(overseerr_media_id: int, tmdb_id: int, title: str) -> bool:
    """
    Update TV show season count by checking ALL Overseerr requests for the same media ID
    This ensures we capture all seasons from all requests, not just the current one
    
    Args:
        overseerr_media_id (int): Overseerr media ID
        tmdb_id (int): TMDB ID of the TV show
        title (str): Title of the TV show for logging
        
    Returns:
        bool: True if update was successful or no update needed
    """
    try:
        from seerr.overseerr import get_all_overseerr_requests_for_media
        
        # Get all requests for this media ID
        all_requests = get_all_overseerr_requests_for_media(overseerr_media_id)
        
        if not all_requests:
            log_warning("Season Count Update", f"No Overseerr requests found for media ID {overseerr_media_id}")
            return False
        
        # Collect all unique season numbers from all requests
        all_requested_seasons = set()
        for request in all_requests:
            if 'seasons' in request and request['seasons']:
                seasons = [season['seasonNumber'] for season in request['seasons']]
                all_requested_seasons.update(seasons)
                log_info("Season Count Update", f"Found seasons {seasons} in request {request['id']} for {title}")
        
        if not all_requested_seasons:
            log_info("Season Count Update", f"No season information found in any requests for {title}")
            return True
        
        # Convert to sorted list
        all_requested_seasons = sorted(list(all_requested_seasons))
        log_info("Season Count Update", f"All unique seasons from all requests for {title}: {all_requested_seasons}")
        
        # Update season count with all seasons
        return update_tv_show_season_count(tmdb_id, all_requested_seasons, title)
        
    except Exception as e:
        log_error("Database Error", f"Error in comprehensive season count update for {title} (Media ID: {overseerr_media_id}): {e}")
        return False