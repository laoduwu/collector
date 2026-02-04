/**
 * Cloudflare Workers - 飞书Webhook接收器
 *
 * 功能：
 * 1. 接收飞书机器人消息
 * 2. 验证飞书签名
 * 3. 提取消息中的URL
 * 4. 触发GitHub Actions
 */

// 环境变量配置（在Cloudflare Workers中设置）
// - FEISHU_VERIFICATION_TOKEN: 飞书验证token
// - FEISHU_ENCRYPT_KEY: 飞书加密key（可选）
// - GH_TOKEN: GitHub Personal Access Token
// - GH_REPO: GitHub仓库名（格式：owner/repo）

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

/**
 * 处理HTTP请求
 */
async function handleRequest(request) {
  // 只接受POST请求
  if (request.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 })
  }

  try {
    // 解析请求体
    const body = await request.json()

    // 处理飞书事件回调验证
    if (body.type === 'url_verification') {
      return handleUrlVerification(body)
    }

    // 处理消息事件
    if (body.header && body.header.event_type === 'im.message.receive_v1') {
      return await handleMessageEvent(body, request)
    }

    // 其他事件类型，返回成功
    return new Response(JSON.stringify({ code: 0 }), {
      headers: { 'Content-Type': 'application/json' }
    })

  } catch (error) {
    console.error('Error handling request:', error)
    return new Response(JSON.stringify({
      code: 1,
      message: error.message
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

/**
 * 处理URL验证事件
 */
function handleUrlVerification(body) {
  console.log('Handling URL verification')
  return new Response(JSON.stringify({
    challenge: body.challenge
  }), {
    headers: { 'Content-Type': 'application/json' }
  })
}

/**
 * 处理消息事件
 */
async function handleMessageEvent(body, request) {
  console.log('Handling message event')

  // 验证签名（可选，推荐在生产环境启用）
  // const isValid = await verifySignature(request, body)
  // if (!isValid) {
  //   return new Response('Invalid signature', { status: 401 })
  // }

  // 提取消息内容
  const event = body.event
  if (!event || !event.message) {
    return new Response(JSON.stringify({ code: 0 }), {
      headers: { 'Content-Type': 'application/json' }
    })
  }

  // 解析消息内容
  const messageContent = JSON.parse(event.message.content || '{}')
  const text = messageContent.text || ''

  // 提取URL
  const url = extractURL(text)
  if (!url) {
    console.log('No URL found in message:', text)
    return new Response(JSON.stringify({ code: 0 }), {
      headers: { 'Content-Type': 'application/json' }
    })
  }

  console.log('Extracted URL:', url)

  // 触发GitHub Actions
  await triggerGitHubActions(url)

  return new Response(JSON.stringify({ code: 0 }), {
    headers: { 'Content-Type': 'application/json' }
  })
}

/**
 * 从文本中提取URL
 */
function extractURL(text) {
  // URL正则表达式
  const urlRegex = /(https?:\/\/[^\s]+)/gi
  const matches = text.match(urlRegex)

  if (matches && matches.length > 0) {
    // 返回第一个URL
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

/**
 * 验证飞书签名（可选）
 */
async function verifySignature(request, body) {
  const signature = request.headers.get('X-Lark-Signature')
  const timestamp = request.headers.get('X-Lark-Request-Timestamp')
  const nonce = request.headers.get('X-Lark-Request-Nonce')

  if (!signature || !timestamp || !nonce) {
    return false
  }

  // 验证时间戳（防重放攻击）
  const currentTime = Math.floor(Date.now() / 1000)
  if (Math.abs(currentTime - parseInt(timestamp)) > 300) {
    return false
  }

  // 计算签名
  const verificationToken = FEISHU_VERIFICATION_TOKEN || ''
  const encryptKey = FEISHU_ENCRYPT_KEY || ''

  const stringToSign = timestamp + nonce + encryptKey + JSON.stringify(body)

  // 使用SHA256计算签名
  const encoder = new TextEncoder()
  const data = encoder.encode(stringToSign)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  const calculatedSignature = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')

  return calculatedSignature === signature
}
