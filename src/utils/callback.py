"""Supabase actions-callback HTTP 回调封装。"""
import os
from typing import Any, Dict

import requests

CALLBACK_TIMEOUT_SEC = 30


def post_callback(payload: Dict[str, Any]) -> None:
    """向 Supabase actions-callback 回写抓取结果。

    必需环境变量：
    - CALLBACK_URL：完整回调 URL
    - CALLBACK_TOKEN：X-Callback-Token 共享密钥
    """
    callback_url = os.environ["CALLBACK_URL"]
    callback_token = os.environ["CALLBACK_TOKEN"]
    resp = requests.post(
        callback_url,
        json=payload,
        headers={"X-Callback-Token": callback_token},
        timeout=CALLBACK_TIMEOUT_SEC,
    )
    resp.raise_for_status()
