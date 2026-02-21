export default defineEventHandler(async (event) => {
  try {
    const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    const response = await fetch(`${backendUrl}/api/processing/stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    })
    
    if (!response.ok) {
      const errorText = await response.text()
      throw createError({
        statusCode: response.status,
        statusMessage: errorText || 'Failed to stop current processing'
      })
    }
    
    return await response.json()
  } catch (error: any) {
    console.error('Error stopping current processing:', error)
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to stop current processing'
    })
  }
})

