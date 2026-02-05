/**
 * Cloudflare Workers - 飞书Webhook接收器（优化版）
 */

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  // 立即记录所有请求
  console.log(`===== REQUEST RECEIVED =====`)
  console.log(`Method: ${request.method}`)
  console.log(`URL: ${request.url}`)
  console.log(`Headers:`, JSON.stringify([...request.headers.entries()]))

  // 处理OPTIONS预检请求（CORS）
  if (request.method === 'OPTIONS') {
    console.log('Handling OPTIONS request')
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      }
    })
  }

  // 添加GET请求支持用于测试
  if (request.method === 'GET') {
    console.log('Handling GET request (test endpoint)')
    return new Response(JSON.stringify({
      status: 'Worker is running!',
      timestamp: new Date().toISOString(),
      message: 'This Feishu webhook receiver is working correctly.'
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    })
  }

  // 只接受POST请求（用于实际webhook）
  if (request.method !== 'POST') {
    console.log(`Rejecting ${request.method} request`)
    return new Response('Method Not Allowed', { status: 405 })
  }

  try {
    // 解析请求体
    const body = await request.json()
    console.log('Received request:', JSON.stringify(body))

    // 方式1: 处理飞书事件回调验证（旧格式）
    if (body.type === 'url_verification') {
      console.log('URL verification (old format):', body.challenge)
      return new Response(JSON.stringify({
        challenge: body.challenge
      }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      })
    }

    // 方式2: 处理飞书事件回调验证（新格式）
    if (body.challenge) {
      console.log('URL verification (new format):', body.challenge)
      return new Response(JSON.stringify({
        challenge: body.challenge
      }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      })
    }

    // 处理消息事件（v2.0格式）
    if (body.header && body.header.event_type === 'im.message.receive_v1') {
      console.log('Message event received')
      await handleMessageEvent(body)
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      })
    }

    // 处理消息事件（旧格式）
    if (body.event && body.event.message) {
      console.log('Message event received (old format)')
      await handleMessageEventOld(body)
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      })
    }

    // 其他事件类型，返回成功
    console.log('Other event type, returning success')
    return new Response(JSON.stringify({ code: 0 }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    })

  } catch (error) {
    console.error('Error handling request:', error)
    return new Response(JSON.stringify({
      code: 1,
      message: error.message
    }), {
      status: 200,  // 仍然返回200，避免飞书重试
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    })
  }
}

/**
 * 处理消息事件（v2.0格式）
 */
async function handleMessageEvent(body) {
  try {
    const event = body.event
    if (!event || !event.message) {
      console.log('No message in event')
      return
    }

    // 解析消息内容
    const messageContent = JSON.parse(event.message.content || '{}')
    const text = messageContent.text || ''

    // 提取URL
    const url = extractURL(text)
    if (!url) {
      console.log('No URL found in message:', text)
      return
    }

    console.log('Extracted URL:', url)

    // 触发GitHub Actions
    await triggerGitHubActions(url)
  } catch (error) {
    console.error('Error handling message event:', error)
    throw error
  }
}

/**
 * 处理消息事件（旧格式）
 */
async function handleMessageEventOld(body) {
  try {
    const event = body.event
    const text = event.text || ''

    const url = extractURL(text)
    if (!url) {
      console.log('No URL found in old format message:', text)
      return
    }

    console.log('Extracted URL (old format):', url)
    await triggerGitHubActions(url)
  } catch (error) {
    console.error('Error handling old format message:', error)
    throw error
  }
}

/**
 * 从文本中提取URL
 */
function extractURL(text) {
  const urlRegex = /(https?:\/\/[^\s]+)/gi
  const matches = text.match(urlRegex)

  if (matches && matches.length > 0) {
    return matches[0]
  }

  return null
}

/**
 * 触发GitHub Actions
 */
async function triggerGitHubActions(url) {
  const githubToken = GH_TOKEN
  const githubRepo = GH_REPO

  if (!githubToken || !githubRepo) {
    console.error('GitHub configuration missing')
    throw new Error('GitHub configuration missing')
  }

  const apiUrl = `https://api.github.com/repos/${githubRepo}/dispatches`
  console.log('Triggering GitHub Actions:', apiUrl)

  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${githubToken}`,
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json',
      'User-Agent': 'Feishu-Webhook-Receiver'
    },
    body: JSON.stringify({
      event_type: 'scrape-article',
      client_payload: {
        url: url,
        timestamp: new Date().toISOString()
      }
    })
  })

  if (!response.ok) {
    const error = await response.text()
    console.error('GitHub API error:', error)
    throw new Error(`Failed to trigger GitHub Actions: ${response.status}`)
  }

  console.log('GitHub Actions triggered successfully')
}
