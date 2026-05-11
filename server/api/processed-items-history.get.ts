export default defineEventHandler(async (event): Promise<any> => {
  const query = getQuery(event)
  const page = Number.parseInt((query.page as string) || '1', 10) || 1
  const limit = Number.parseInt((query.limit as string) || '100', 10) || 100
  const seerrbridgeUrl = process.env.SEERRBRIDGE_URL || 'http://localhost:8777'

  try {
    const response: any = await $fetch(`${seerrbridgeUrl}/api/processed-items-history`, {
      method: 'GET',
      query: {
        page,
        limit
      }
    })
    return response
  } catch (error: any) {
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || 'Failed to fetch processed item history'
    })
  }
})
