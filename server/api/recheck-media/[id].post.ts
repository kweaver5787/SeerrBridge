export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id')

  if (!id) {
    throw createError({
      statusCode: 400,
      statusMessage: 'Media ID is required'
    })
  }

  const body = await readBody(event).catch(() => ({}))
  const backendBody: Record<string, unknown> = {}
  if (body?.season_number !== undefined && body?.season_number !== null) {
    backendBody.season_number = body.season_number
  }
  if (body?.episode_numbers !== undefined && Array.isArray(body.episode_numbers)) {
    backendBody.episode_numbers = body.episode_numbers
  }

  const seerrbridgeUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'

  try {
    const response = await $fetch(`${seerrbridgeUrl}/recheck-media/${id}`, {
      method: 'POST',
      body: Object.keys(backendBody).length ? backendBody : undefined,
      headers: Object.keys(backendBody).length ? { 'Content-Type': 'application/json' } : undefined
    })

    return response
  } catch (error: any) {
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to recheck media'
    })
  }
})
