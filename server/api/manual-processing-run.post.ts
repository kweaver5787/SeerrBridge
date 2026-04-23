import { defineEventHandler } from 'h3'

export default defineEventHandler(async () => {
  try {
    const pythonBackendUrl = process.env.PYTHON_BACKEND_URL || 'http://seerrbridge:8777'

    const response = await fetch(`${pythonBackendUrl}/api/manual-processing-run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      throw new Error(`Python backend responded with status: ${response.status}`)
    }

    const result = await response.json()

    return {
      success: true,
      message: result?.message || 'Manual Processing Run completed successfully',
      data: result,
    }
  } catch (error: any) {
    console.error('Error triggering Manual Processing Run:', error)
    return {
      success: false,
      error: 'Failed to trigger Manual Processing Run',
      details: error?.message || 'Unknown error',
    }
  }
})
