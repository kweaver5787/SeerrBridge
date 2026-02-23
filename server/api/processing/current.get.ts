export default defineEventHandler(async (event) => {
  const backendUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'

  try {
    const response = await fetch(`${backendUrl}/api/processing/current`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    })

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`)
    }

    return await response.json()
  } catch (error: any) {
    // Backend not ready yet (ECONNREFUSED) or other network/backend error:
    // return safe response so UI keeps polling instead of throwing
    const cause = error?.cause?.code || error?.code
    if (cause === 'ECONNREFUSED' || cause === 'ECONNRESET' || cause === 'ETIMEDOUT') {
      return {
        success: true,
        processing: false,
        message: 'Backend not ready yet'
      }
    }
    // Log other errors but still return safe response to avoid layout break
    console.error('Error getting currently processing item:', error)
    return {
      success: true,
      processing: false,
      message: 'Failed to get currently processing item'
    }
  }
})

