export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, 'id')
    if (!id) {
      throw createError({
        statusCode: 400,
        statusMessage: 'Media ID is required'
      })
    }
    
    const body = await readBody(event).catch(() => ({}))
    const forceImageRefresh = body.force_image_refresh || false
    
    // Call Python backend to refresh Trakt data
    const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    const response = await fetch(`${backendUrl}/api/media/${id}/refresh-trakt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        force_image_refresh: forceImageRefresh
      })
    })
    
    if (!response.ok) {
      const errorText = await response.text()
      throw createError({
        statusCode: response.status,
        statusMessage: errorText || 'Failed to refresh Trakt data'
      })
    }
    
    const result = await response.json()
    
    return {
      success: true,
      message: result.message || 'Successfully refreshed Trakt data',
      media_id: result.media_id
    }
  } catch (error: any) {
    console.error('Error refreshing Trakt data:', error)
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to refresh Trakt data'
    })
  }
})

