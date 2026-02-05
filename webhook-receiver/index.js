/**
 * Cloudflare Workers - 飞书Webhook接收器
 * 支持 Encrypt Key 加密解密
 */

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

/**
 * 解密飞书加密消息
 * @param {string} encrypt - Base64编码的加密字符串
 * @param {string} encryptKey - 飞书应用的 Encrypt Key
 * @returns {Promise<object>} 解密后的JSON对象
 */
async function decryptFeishuMessage(encrypt, encryptKey) {
  // 1. SHA-256 哈希 Encrypt Key 得到 32 字节密钥
  const encoder = new TextEncoder()
  const keyData = encoder.encode(encryptKey)
  const hashBuffer = await crypto.subtle.digest('SHA-256', keyData)

  // 2. Base64 解码加密字符串
  const encryptedBuffer = Uint8Array.from(atob(encrypt), c => c.charCodeAt(0))

  // 3. 前16字节是IV，剩余是加密数据
  const iv = encryptedBuffer.slice(0, 16)
  const encryptedData = encryptedBuffer.slice(16)

  // 4. 导入密钥
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    hashBuffer,
    { name: 'AES-CBC' },
    false,
    ['decrypt']
  )

  // 5. AES-256-CBC 解密
  const decryptedBuffer = await crypto.subtle.decrypt(
    { name: 'AES-CBC', iv: iv },
    cryptoKey,
    encryptedData
  )

  // 6. 转换为字符串并解析JSON
  const decoder = new TextDecoder()
  let decryptedText = decoder.decode(decryptedBuffer)

  // 7. 移除PKCS7填充（最后一个字节表示填充长度）
  const paddingLength = decryptedText.charCodeAt(decryptedText.length - 1)
  if (paddingLength > 0 && paddingLength <= 16) {
    decryptedText = decryptedText.slice(0, -paddingLength)
  }

  console.log('Decrypted message:', decryptedText)
  return JSON.parse(decryptedText)
}

async function handleRequest(request) {
  console.log(`===== REQUEST RECEIVED =====`)
  console.log(`Method: ${request.method}`)
  console.log(`URL: ${request.url}`)

  // 处理OPTIONS预检请求（CORS）
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      }
    })
  }

  // GET请求用于测试
  if (request.method === 'GET') {
    return new Response(JSON.stringify({
      status: 'Worker is running!',
      timestamp: new Date().toISOString(),
      message: 'Feishu webhook receiver with encryption support.'
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  }

  // 只接受POST请求
  if (request.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 })
  }

  try {
    // 解析请求体
    let body = await request.json()
    console.log('Raw request body:', JSON.stringify(body))

    // 检查是否为加密消息
    if (body.encrypt && typeof FEISHU_ENCRYPT_KEY !== 'undefined' && FEISHU_ENCRYPT_KEY) {
      console.log('Encrypted message detected, decrypting...')
      try {
        body = await decryptFeishuMessage(body.encrypt, FEISHU_ENCRYPT_KEY)
        console.log('Decryption successful')
      } catch (decryptError) {
        console.error('Decryption failed:', decryptError)
        return new Response(JSON.stringify({
          code: 1,
          message: 'Decryption failed: ' + decryptError.message
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      }
    }

    // 处理 URL 验证（challenge）
    if (body.type === 'url_verification' || body.challenge) {
      console.log('URL verification, challenge:', body.challenge)
      return new Response(JSON.stringify({
        challenge: body.challenge
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    // 处理消息事件（v2.0格式）
    if (body.header && body.header.event_type === 'im.message.receive_v1') {
      console.log('Message event received (v2.0)')
      await handleMessageEvent(body)
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    // 处理消息事件（旧格式）
    if (body.event && body.event.message) {
      console.log('Message event received (old format)')
      await handleMessageEventOld(body)
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    // 其他事件类型
    console.log('Other event type, returning success')
    return new Response(JSON.stringify({ code: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })

  } catch (error) {
    console.error('Error handling request:', error)
    return new Response(JSON.stringify({
      code: 1,
      message: error.message
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

/**
 * 处理消息事件（v2.0格式）
 */
async function handleMessageEvent(body) {
  const event = body.event
  if (!event || !event.message) {
    console.log('No message in event')
    return
  }

  const messageContent = JSON.parse(event.message.content || '{}')
  const text = messageContent.text || ''

  const url = extractURL(text)
  if (!url) {
    console.log('No URL found in message:', text)
    return
  }

  console.log('Extracted URL:', url)
  await triggerGitHubActions(url)
}

/**
 * 处理消息事件（旧格式）
 */
async function handleMessageEventOld(body) {
  const event = body.event
  const text = event.text || ''

  const url = extractURL(text)
  if (!url) {
    console.log('No URL found in message:', text)
    return
  }

  console.log('Extracted URL:', url)
  await triggerGitHubActions(url)
}

/**
 * 从文本中提取URL
 */
function extractURL(text) {
  const urlRegex = /(https?:\/\/[^\s]+)/gi
  const matches = text.match(urlRegex)
  return matches && matches.length > 0 ? matches[0] : null
}

/**
 * 触发GitHub Actions
 */
async function triggerGitHubActions(url) {
  const githubToken = typeof GH_TOKEN !== 'undefined' ? GH_TOKEN : ''
  const githubRepo = typeof GH_REPO !== 'undefined' ? GH_REPO : ''

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
