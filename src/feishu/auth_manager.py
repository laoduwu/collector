"""飞书认证管理器"""
import time
from typing import Optional
import lark_oapi as lark
from lark_oapi.api.auth.v3 import InternalTenantAccessTokenRequest
from utils.logger import logger
from utils.config import config


class AuthManager:
    """飞书认证管理器"""

    def __init__(self):
        if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET must be configured")

        self.app_id = config.FEISHU_APP_ID
        self.app_secret = config.FEISHU_APP_SECRET
        self._access_token: Optional[str] = None
        self._token_expire_time: float = 0

        # 创建飞书客户端
        self.client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .log_level(lark.LogLevel.ERROR) \
            .build()

    def get_access_token(self) -> str:
        """
        获取tenant_access_token（自动刷新）

        Returns:
            access token

        Raises:
            Exception: 获取token失败
        """
        # 检查token是否仍然有效（提前5分钟刷新）
        current_time = time.time()
        if self._access_token and current_time < self._token_expire_time - 300:
            return self._access_token

        # 获取新token
        logger.info("Fetching new Feishu access token...")

        try:
            request = InternalTenantAccessTokenRequest.builder() \
                .request_body(
                    InternalTenantAccessTokenRequest.InternalTenantAccessTokenRequestBody.builder()
                    .app_id(self.app_id)
                    .app_secret(self.app_secret)
                    .build()
                ) \
                .build()

            response = self.client.auth.v3.tenant_access_token.internal(request)

            if not response.success():
                logger.error(
                    f"Failed to get access token: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                raise Exception(f"Failed to get Feishu access token: {response.msg}")

            # 保存token和过期时间
            self._access_token = response.data.tenant_access_token
            # token通常有效期2小时
            self._token_expire_time = current_time + response.data.expire

            logger.info("Successfully obtained Feishu access token")
            return self._access_token

        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            raise

    def invalidate_token(self):
        """使当前token失效（强制刷新）"""
        self._access_token = None
        self._token_expire_time = 0
        logger.info("Access token invalidated")
