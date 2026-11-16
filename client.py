"""MicroLight API client. Credentials never appear in URLs/errors."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MicroLightClient:
    def __init__(self, base_url: str, token: str):
        url = urlsplit(base_url.strip())
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('请填写本站完整根地址，例如 https://goblincwl.site')
        if not re.fullmatch(r'ml_[A-Za-z0-9_-]{43}', token.strip()):
            raise ValueError('请填写在星枢账户配置中生成的有效 API Token')
        self.base = base_url.strip().rstrip('/')
        self.token = token.strip()

    def status(self):
        data = self.call('GET', 'status')
        if data.get('service') != 'MicroLight' or data.get('version') != 1 or not isinstance(data.get('scopes'), list):
            raise ValueError('接收地址未返回 MicroLight API 状态')
        return data

    def call(self, method: str, path: str):
        if method not in ('GET', 'POST', 'DELETE') or not re.fullmatch(r'[A-Za-z0-9_/?=&-]+', path) or '..' in path:
            raise ValueError('API 操作参数无效')
        request = Request(self.base+'/api/microlight/v1/'+path, method=method,
                          headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/json'})
        try:
            with build_opener(NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise ValueError('本站 API 响应过大')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('本站 API 响应格式无效')
                return data
        except HTTPError as error:
            raise ValueError(f'本站 API 操作失败（HTTP {error.code}）') from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('无法连接本站 API 或连接超时') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('本站 API 响应格式无效') from None
