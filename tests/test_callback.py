import os
from unittest.mock import patch, MagicMock
import pytest
from utils.callback import post_callback


def test_post_callback_sends_token_and_payload(monkeypatch):
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 'tok-123')

    fake = MagicMock()
    fake.raise_for_status.return_value = None

    with patch('utils.callback.requests.post', return_value=fake) as p:
        post_callback({'article_id': 'a-1', 'status': 'success', 'title': 'T'})
        args, kwargs = p.call_args
        assert args[0] == 'https://x.supabase.co/functions/v1/actions-callback'
        assert kwargs['headers']['X-Callback-Token'] == 'tok-123'
        assert kwargs['json']['article_id'] == 'a-1'
        assert kwargs['timeout'] == 30


def test_post_callback_raises_on_http_error(monkeypatch):
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 'tok-123')

    fake = MagicMock()
    fake.raise_for_status.side_effect = RuntimeError('500')

    with patch('utils.callback.requests.post', return_value=fake):
        with pytest.raises(RuntimeError):
            post_callback({'article_id': 'a-1', 'status': 'error'})
