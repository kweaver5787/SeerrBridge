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
    const checkSeerr = body.check_seerr !== false // Default to true
    
    // Call Python backend
    const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    const response = await fetch(`${backendUrl}/api/media/${id}/mark-complete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        check_seerr: checkSeerr
      })
    })
    
    if (!response.ok) {
      const errorText = await response.text()
      throw createError({
        statusCode: response.status,
        statusMessage: errorText || 'Failed to mark media as complete'
      })
    }
    
    const result = await response.json()
    
    return {
      success: true,
      message: result.message || 'Successfully marked media as complete',
      media_id: result.media_id
    }
  } catch (error: any) {
    console.error('Error marking media as complete:', error)
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to mark media as complete'
    })
  }
})

