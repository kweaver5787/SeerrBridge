export default defineEventHandler(async (event) => {
  try {
    const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    const response = await fetch(`${backendUrl}/api/processing/current`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    })
    
    if (!response.ok) {
      throw createError({
        statusCode: response.status,
        statusMessage: 'Failed to get currently processing item'
      })
    }
    
    return await response.json()
  } catch (error: any) {
    console.error('Error getting currently processing item:', error)
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to get currently processing item'
    })
  }
})

