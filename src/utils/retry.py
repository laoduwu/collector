"""重试逻辑工具"""
import time
import random
from typing import Callable, TypeVar, Optional
from functools import wraps
from .logger import logger

T = TypeVar('T')


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    带指数退避的重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数基数
        jitter: 是否添加随机抖动
        exceptions: 需要重试的异常类型元组

    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        # 最后一次尝试失败
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {str(e)}")
                        raise

                    # 计算延迟时间
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)

                    # 添加随机抖动
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed: {str(e)}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    time.sleep(delay)

            # 理论上不会到这里，但为了类型检查
            if last_exception:
                raise last_exception
            return None  # type: ignore

        return wrapper
    return decorator


async def async_retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    异步版本的重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数基数
        jitter: 是否添加随机抖动
        exceptions: 需要重试的异常类型元组

    Returns:
        装饰器函数
    """
    import asyncio

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {str(e)}")
                        raise

                    delay = min(base_delay * (exponential_base ** attempt), max_delay)

                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed: {str(e)}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception
            return None  # type: ignore

        return wrapper
    return decorator
