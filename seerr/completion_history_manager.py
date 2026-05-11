"""
Helpers for recording first-time processed item history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy.exc import IntegrityError

from seerr.database import ProcessedItemHistory, get_db
from seerr.db_logger import log_error, log_info
from seerr.unified_models import UnifiedMedia


def _episode_sort_key(episode_id: str) -> int:
    try:
        return int(str(episode_id).replace("E", ""))
    except Exception:
        return 0


def _build_item_key(media: UnifiedMedia, season_number: Optional[int], episode_id: Optional[str]) -> str:
    if media.media_type == "movie":
        base_id = media.tmdb_id or media.id
        return f"movie:{base_id}"

    if season_number is None or not episode_id:
        raise ValueError("TV history entries require season_number and episode_id")
    return f"tv:{media.id}:S{int(season_number):02d}{str(episode_id).upper()}"


def _build_display_name(media: UnifiedMedia, season_number: Optional[int], episode_id: Optional[str]) -> str:
    if media.media_type == "movie":
        return media.title
    return f"{media.title} S{int(season_number):02d}{str(episode_id).upper()}"


def record_processed_item(
    media: UnifiedMedia,
    *,
    source: str,
    season_number: Optional[int] = None,
    episode_id: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    db=None,
) -> bool:
    """
    Insert first-time processed item history record.
    Returns True if inserted, False when it already exists or on failure.
    """
    own_session = db is None
    session = db or get_db()
    try:
        item_key = _build_item_key(media, season_number, episode_id)
        existing = session.query(ProcessedItemHistory.id).filter(
            ProcessedItemHistory.item_key == item_key
        ).first()
        if existing:
            return False

        entry = ProcessedItemHistory(
            item_key=item_key,
            unified_media_id=media.id,
            media_type=media.media_type,
            title=media.title,
            season_number=int(season_number) if season_number is not None else None,
            episode_id=str(episode_id).upper() if episode_id else None,
            display_name=_build_display_name(media, season_number, episode_id),
            completion_source=source,
            completed_at=completed_at or datetime.utcnow(),
        )
        session.add(entry)
        if own_session:
            session.commit()
        return True
    except IntegrityError:
        if own_session:
            session.rollback()
        return False
    except Exception as exc:
        if own_session:
            session.rollback()
        log_error(
            "Completion History",
            f"Failed to record processed item: {exc}",
            module="completion_history_manager",
            function="record_processed_item",
        )
        return False
    finally:
        if own_session:
            session.close()


def record_processed_movie(media: UnifiedMedia, *, source: str, completed_at: Optional[datetime] = None, db=None) -> bool:
    if media.media_type != "movie":
        return False
    return record_processed_item(media, source=source, completed_at=completed_at, db=db)


def record_processed_tv_episode(
    media: UnifiedMedia,
    *,
    season_number: int,
    episode_id: str,
    source: str,
    completed_at: Optional[datetime] = None,
    db=None,
) -> bool:
    if media.media_type != "tv":
        return False
    return record_processed_item(
        media,
        source=source,
        season_number=season_number,
        episode_id=episode_id,
        completed_at=completed_at,
        db=db,
    )


def sync_tv_history_from_seasons_data(media: UnifiedMedia, *, source: str, db=None) -> int:
    """
    Backfill/ensure history rows for all currently confirmed TV episodes.
    """
    if media.media_type != "tv":
        return 0
    seasons_data = media.seasons_data or []
    if isinstance(seasons_data, str):
        import json

        try:
            seasons_data = json.loads(seasons_data) if seasons_data else []
        except Exception:
            seasons_data = []

    inserted = 0
    for season in seasons_data:
        if not isinstance(season, dict):
            continue
        season_number = season.get("season_number")
        if season_number is None:
            continue
        confirmed = sorted((season.get("confirmed_episodes") or []), key=_episode_sort_key)
        for episode_id in confirmed:
            if not isinstance(episode_id, str) or not episode_id.startswith("E"):
                continue
            if record_processed_tv_episode(
                media,
                season_number=int(season_number),
                episode_id=episode_id,
                source=source,
                completed_at=media.processing_completed_at or datetime.utcnow(),
                db=db,
            ):
                inserted += 1
    return inserted


def backfill_processed_history() -> dict[str, int]:
    """
    Idempotent backfill for existing completed movies and confirmed TV episodes.
    """
    db = get_db()
    inserted_movies = 0
    inserted_episodes = 0
    try:
        completed_movies = db.query(UnifiedMedia).filter(
            UnifiedMedia.media_type == "movie",
            UnifiedMedia.status == "completed",
        ).all()
        for media in completed_movies:
            if record_processed_movie(
                media,
                source="backfill",
                completed_at=media.processing_completed_at or media.updated_at or datetime.utcnow(),
                db=db,
            ):
                inserted_movies += 1

        tv_items = db.query(UnifiedMedia).filter(
            UnifiedMedia.media_type == "tv",
            UnifiedMedia.seasons_data.isnot(None),
        ).all()
        for media in tv_items:
            inserted_episodes += sync_tv_history_from_seasons_data(media, source="backfill", db=db)

        db.commit()
        if inserted_movies or inserted_episodes:
            log_info(
                "Completion History",
                f"Backfill inserted {inserted_movies} movies and {inserted_episodes} TV episodes",
                module="completion_history_manager",
                function="backfill_processed_history",
            )
        return {"movies": inserted_movies, "episodes": inserted_episodes}
    except Exception as exc:
        db.rollback()
        log_error(
            "Completion History",
            f"Backfill failed: {exc}",
            module="completion_history_manager",
            function="backfill_processed_history",
        )
        return {"movies": 0, "episodes": 0}
    finally:
        db.close()
