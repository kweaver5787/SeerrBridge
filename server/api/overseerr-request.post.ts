import { getOverseerrConfig } from '~/server/utils/overseerr-config'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    const { mediaId, mediaType, is4k = false, seasons } = body
    
    if (!mediaId || !mediaType) {
      return {
        success: false,
        error: 'Missing required parameters: mediaId and mediaType'
      }
    }
    
    // Get Overseerr configuration
    const { baseUrl: overseerrBaseUrl, apiKey: overseerrApiKey } = await getOverseerrConfig()
    
    if (!overseerrBaseUrl) {
      return {
        success: false,
        error: 'Overseerr base URL not configured'
      }
    }
    
    if (!overseerrApiKey) {
      return {
        success: false,
        error: 'Overseerr API key not configured'
      }
    }
    
    // Remove trailing slash from base URL
    const baseUrl = overseerrBaseUrl.replace(/\/$/, '')
    
    // Construct Overseerr request API URL
    const requestUrl = `${baseUrl}/api/v1/request`
    
    // Prepare request body
    const requestBody: any = {
      mediaType,
      mediaId,
      is4k
    }
    
    // Add seasons for TV shows
    if (mediaType === 'tv' && seasons && Array.isArray(seasons)) {
      requestBody.seasons = seasons
    }
    
    // Make request to Overseerr API
    const response = await fetch(requestUrl, {
      method: 'POST',
      headers: {
        'X-Api-Key': overseerrApiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestBody)
    })
    
    if (!response.ok) {
      const errorText = await response.text()
      return {
        success: false,
        error: `Overseerr API error: ${response.status} ${response.statusText}`,
        details: errorText
      }
    }
    
    const data = await response.json()
    
    // After successful request, trigger seerrbridge processing via webhook
    // Get seerrbridge URL from environment or config
    const seerrbridgeUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    const webhookUrl = `${seerrbridgeUrl}/jellyseer-webhook/`
    
    try {
      // Extract request details from Overseerr/Jellyseerr response (handle multiple response shapes)
      let requestId = data.id ?? data.request?.id ?? data.requestId ?? data.data?.id ?? data.data?.request?.id
      let mediaInfo = data.media ?? data.request?.media ?? data.data?.media ?? data.data?.request?.media
      let requestInfo = data.request ?? data.data?.request ?? data

      // If we don't have complete info, try to fetch the request details by id
      let fullRequestData = data
      if (requestId && (!mediaInfo || !requestInfo?.requestedBy)) {
        try {
          const requestDetailsResponse = await fetch(`${baseUrl}/api/v1/request/${requestId}`, {
            headers: {
              'X-Api-Key': overseerrApiKey
            }
          })
          if (requestDetailsResponse.ok) {
            fullRequestData = await requestDetailsResponse.json()
          }
        } catch (fetchError) {
          console.warn('Could not fetch request details, using response data:', fetchError)
        }
      }

      // Use full request data if available
      let finalMediaInfo = fullRequestData.media ?? fullRequestData.request?.media ?? mediaInfo
      let finalRequestInfo = fullRequestData.request ?? fullRequestData

      // Fallback: when adding a season to an existing show, response may lack id/media — fetch requests and find by mediaId
      if ((!requestId || !finalMediaInfo) && mediaId) {
        try {
          const listResponse = await fetch(`${baseUrl}/api/v1/request?take=500&filter=all&sort=added`, {
            headers: { 'X-Api-Key': overseerrApiKey }
          })
          if (listResponse.ok) {
            const listData = await listResponse.json()
            const results = listData.results ?? listData ?? []
            const requests = Array.isArray(results) ? results : []
            const match = requests.find((r: any) => {
              const m = r.media ?? r
              const tid = m.tmdbId ?? m.tmdb_id
              return Number(tid) === Number(mediaId)
            })
            if (match) {
              requestId = requestId ?? match.id
              finalMediaInfo = finalMediaInfo ?? match.media ?? match
              finalRequestInfo = finalRequestInfo ?? match
            }
          }
        } catch (fetchError) {
          console.warn('Could not fetch request list for fallback:', fetchError)
        }
      }

      if (requestId && finalMediaInfo) {
        // Construct webhook payload
        const webhookPayload = {
          notification_type: 'MEDIA_REQUESTED',
          event: 'media.requested',
          subject: `${mediaType === 'tv' ? 'TV Show' : 'Movie'} Request`,
          message: `A ${mediaType === 'tv' ? 'TV show' : 'movie'} has been requested`,
          media: {
            media_type: mediaType,
            tmdbId: finalMediaInfo.tmdbId || mediaId,
            tvdbId: finalMediaInfo.tvdbId || null,
            status: String(finalMediaInfo.status || '3'),
            status4k: String(finalMediaInfo.status4k || '3')
          },
          request: {
            request_id: String(requestId),
            requestedBy_email: finalRequestInfo.requestedBy?.email || finalRequestInfo.requestedBy_email || 'system@seerrbridge.local',
            requestedBy_username: finalRequestInfo.requestedBy?.username || finalRequestInfo.requestedBy?.displayName || finalRequestInfo.requestedBy_username || 'System',
            requestedBy_avatar: finalRequestInfo.requestedBy?.avatar || finalRequestInfo.requestedBy_avatar || '',
            requestedBy_settings_discordId: finalRequestInfo.requestedBy?.settings?.discordId || finalRequestInfo.requestedBy_settings_discordId || null,
            requestedBy_settings_telegramChatId: finalRequestInfo.requestedBy?.settings?.telegramChatId || finalRequestInfo.requestedBy_settings_telegramChatId || null
          },
          extra: seasons ? [{ requested_seasons: seasons }] : []
        }
        
        // Call seerrbridge webhook asynchronously (don't wait for response)
        fetch(webhookUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(webhookPayload)
        }).catch((webhookError) => {
          // Log webhook error but don't fail the request
          console.error('Failed to trigger seerrbridge webhook:', webhookError)
        })
      } else {
        console.warn('Could not construct webhook payload - missing requestId or mediaInfo', { requestId, hasMediaInfo: !!finalMediaInfo })
      }
    } catch (webhookError) {
      // Log webhook error but don't fail the request
      console.error('Error constructing webhook payload:', webhookError)
    }
    
    return {
      success: true,
      data: data,
      message: 'Request created successfully'
    }
    
  } catch (error) {
    console.error('Error creating Overseerr request:', error)
    return {
      success: false,
      error: 'Failed to create request',
      details: error instanceof Error ? error.message : String(error)
    }
  }
})

