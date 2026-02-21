import { getDatabaseConnection } from '~/server/utils/database'

interface SubscribeRequest {
  tmdb_id: number
  mark_existing_completed?: boolean
}

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody<SubscribeRequest>(event)
    
    if (!body.tmdb_id) {
      throw createError({
        statusCode: 400,
        statusMessage: 'TMDB ID is required'
      })
    }
    
    // Call Python backend to subscribe
    const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'
    console.log(`[Subscribe] Calling backend: ${backendUrl}/api/tv-subscriptions/subscribe`)
    const response = await fetch(`${backendUrl}/api/tv-subscriptions/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        tmdb_id: body.tmdb_id,
        mark_existing_completed: body.mark_existing_completed !== false // Default to true
      })
    })
    
    if (!response.ok) {
      const errorText = await response.text()
      throw createError({
        statusCode: response.status,
        statusMessage: errorText || 'Failed to subscribe to show'
      })
    }
    
    const result = await response.json()
    
    return {
      success: true,
      message: `Successfully subscribed to show`,
      media_id: result.media_id
    }
  } catch (error: any) {
    console.error('Error subscribing to show:', error)
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to subscribe to show'
    })
  }
})

