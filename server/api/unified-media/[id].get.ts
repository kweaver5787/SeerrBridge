import { getDatabaseConnection } from '~/server/utils/database'

export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, 'id')
    if (!id) {
      throw createError({
        statusCode: 400,
        statusMessage: 'Media ID is required'
      })
    }

    const db = await getDatabaseConnection()
    
    // Get the media item with all its details
    const [mediaRows] = await db.execute(`
      SELECT 
        um.*,
        CASE 
          WHEN um.status = 'completed' THEN 'completed'
          WHEN um.status = 'processing' THEN 'processing'
          WHEN um.status = 'failed' THEN 'failed'
          WHEN um.status = 'pending' THEN 'pending'
          WHEN um.status = 'skipped' THEN 'skipped'
          WHEN um.status = 'cancelled' THEN 'cancelled'
          WHEN um.status = 'ignored' THEN 'ignored'
          ELSE um.status
        END as display_status,
        CASE 
          WHEN um.media_type = 'tv' AND um.seasons_processed IS NOT NULL THEN
            CASE 
              WHEN JSON_EXTRACT(um.seasons_processed, '$.completed') IS NOT NULL 
                AND JSON_EXTRACT(um.seasons_processed, '$.total') IS NOT NULL THEN
                CONCAT(
                  JSON_EXTRACT(um.seasons_processed, '$.completed'), 
                  '/', 
                  JSON_EXTRACT(um.seasons_processed, '$.total')
                )
              ELSE um.status
            END
          ELSE um.status
        END as status_display,
        CASE 
          WHEN um.media_type = 'tv' AND um.seasons_processed IS NOT NULL THEN
            CASE 
              WHEN JSON_EXTRACT(um.seasons_processed, '$.completed') IS NOT NULL 
                AND JSON_EXTRACT(um.seasons_processed, '$.total') IS NOT NULL THEN
                ROUND(
                  (JSON_EXTRACT(um.seasons_processed, '$.completed') / JSON_EXTRACT(um.seasons_processed, '$.total')) * 100
                )
              ELSE 0
            END
          ELSE 0
        END as progress_percentage
      FROM unified_media um
      WHERE um.id = ?
    `, [id])
    
    const media = (mediaRows as any[])[0]
    if (!media) {
      throw createError({
        statusCode: 404,
        statusMessage: 'Media item not found'
      })
    }
    
    // Parse JSON fields
    if (media.seasons_processed) {
      try {
        media.seasons_processed = JSON.parse(media.seasons_processed)
      } catch (e) {
        media.seasons_processed = null
      }
    }
    
    if (media.extra_data) {
      try {
        media.extra_data = JSON.parse(media.extra_data)
      } catch (e) {
        media.extra_data = null
      }
    }
    
    // Parse seasons_data from unified_media (source of truth for Python backend / mark-complete)
    let seasonsData: any[] = []
    if (media.seasons_data) {
      try {
        seasonsData = typeof media.seasons_data === 'string'
          ? JSON.parse(media.seasons_data)
          : media.seasons_data
        if (!Array.isArray(seasonsData)) seasonsData = []
      } catch (e) {
        seasonsData = []
      }
    }
    
    // Build seasons for TV: prefer unified_media.seasons_data so mark-complete updates are visible
    let seasons: any[] = []
    if (media.media_type === 'tv') {
      if (seasonsData.length > 0) {
        seasons = seasonsData.map((season: any) => ({
          season_number: season.season_number ?? 0,
          episode_count: season.episode_count ?? 0,
          aired_episodes: season.aired_episodes ?? 0,
          failed_episodes: season.failed_episodes ?? [],
          confirmed_episodes: season.confirmed_episodes ?? [],
          unprocessed_episodes: season.unprocessed_episodes ?? [],
          unaired_episodes: season.unaired_episodes ?? [],
          is_discrepant: season.is_discrepant ?? false,
          discrepancy_reason: season.discrepancy_reason ?? null,
          discrepancy_details: season.discrepancy_details ?? {},
          status: season.status ?? 'unknown',
          season_details: season,
          last_checked: season.last_checked,
          updated_at: season.updated_at ?? media.updated_at
        }))
      } else {
        // Fallback to tv_seasons table when seasons_data is empty
        const [seasonRows] = await db.execute(`
          SELECT 
            season_number,
            episode_count,
            aired_episodes,
            confirmed_episodes,
            failed_episodes,
            unprocessed_episodes,
            unaired_episodes,
            is_discrepant,
            discrepancy_reason,
            discrepancy_details,
            status,
            season_details,
            last_checked,
            updated_at
          FROM tv_seasons 
          WHERE media_id = ?
          ORDER BY season_number ASC
        `, [id])
        
        seasons = (seasonRows as any[]).map(season => {
          if (season.confirmed_episodes) {
            try {
              season.confirmed_episodes = JSON.parse(season.confirmed_episodes)
            } catch (e) {
              season.confirmed_episodes = []
            }
          }
          if (season.failed_episodes) {
            try {
              season.failed_episodes = JSON.parse(season.failed_episodes)
            } catch (e) {
              season.failed_episodes = []
            }
          }
          if (season.unprocessed_episodes) {
            try {
              season.unprocessed_episodes = JSON.parse(season.unprocessed_episodes)
            } catch (e) {
              season.unprocessed_episodes = []
            }
          }
          if (season.unaired_episodes) {
            try {
              season.unaired_episodes = JSON.parse(season.unaired_episodes)
            } catch (e) {
              season.unaired_episodes = []
            }
          }
          if (season.discrepancy_details) {
            try {
              season.discrepancy_details = JSON.parse(season.discrepancy_details)
            } catch (e) {
              season.discrepancy_details = null
            }
          }
          if (season.season_details) {
            try {
              season.season_details = JSON.parse(season.season_details)
            } catch (e) {
              season.season_details = null
            }
          }
          return season
        })
      }
    }
    
    media.seasons = seasons
    
    return {
      success: true,
      data: media
    }
  } catch (error) {
    console.error('Error fetching media item:', error)
    throw createError({
      statusCode: 500,
      statusMessage: 'Failed to fetch media item',
      data: error instanceof Error ? error.message : 'Unknown error'
    })
  }
})
