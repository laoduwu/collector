from unittest.mock import patch, MagicMock
import pytest
from scrapers.image_downloader import download_to_bytes


def test_download_to_bytes_returns_filename_and_bytes():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b'fake-image-bytes'
    fake_resp.headers = {'Content-Type': 'image/jpeg'}
    fake_resp.raise_for_status.return_value = None

    with patch('scrapers.image_downloader.requests.get', return_value=fake_resp) as g:
        filename, data = download_to_bytes(
            'https://mmbiz.qpic.cn/abc.jpg',
            referer='https://mp.weixin.qq.com/'
        )
        assert data == b'fake-image-bytes'
        assert filename.endswith('.jpg')
        headers = g.call_args.kwargs['headers']
        assert headers['Referer'] == 'https://mp.weixin.qq.com/'


def test_download_to_bytes_infers_extension_from_content_type():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b'png-bytes'
    fake_resp.headers = {'Content-Type': 'image/png'}
    fake_resp.raise_for_status.return_value = None

    with patch('scrapers.image_downloader.requests.get', return_value=fake_resp):
        filename, data = download_to_bytes('https://x.example/noext')
        assert filename.endswith('.png')
