"""Optional access-code gate for the explicitly enabled LAN entry point."""
import hashlib
import hmac
import secrets

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE_NAME = 'jcc_tablet_session'
DEFAULT_HOSTS = ['127.0.0.1', 'localhost', '[::1]', 'testserver']


def allowed_hosts(extra):
    hosts = list(DEFAULT_HOSTS)
    for value in (extra or '').split(','):
        value = value.strip()
        if not value:
            continue
        if '*' in value or '/' in value or '://' in value:
            raise ValueError('JCC_ALLOWED_HOSTS must list explicit hostnames or IPs, without ports, paths or wildcards')
        if value not in hosts:
            hosts.append(value)
    return hosts


def session_value(token):
    return hmac.new(token.encode('utf-8'), b'jcc-tablet-session-v1', hashlib.sha256).hexdigest()


def matches(value, expected):
    return isinstance(value, str) and secrets.compare_digest(value.encode('utf-8'), expected.encode('utf-8'))


LOGIN_PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>连接弈策</title><style>body{max-width:480px;margin:12vh auto;padding:24px;background:#14202a;color:#dce7ee;font:17px/1.8 system-ui}input,button{font:inherit;width:100%;box-sizing:border-box;padding:14px;border-radius:8px;margin:12px 0}button{background:#bad28d;color:#172117;border:0}p{color:#9aafbc}</style><h1>连接电脑上的弈策</h1><p>用平板扫描电脑显示的二维码，或输入电脑启动时显示的访问码。</p><form action="/tablet-login" method="post"><label for="access-token">访问码</label><input id="access-token" name="access_token" type="password" autocomplete="current-password" required><button type="submit">连接</button></form><p>电脑需要保持开机，并运行平板访问服务。</p></html>'''


async def access_response(request, token):
    """None continues the request; otherwise return a login/denial response."""
    if not token:
        return None
    supplied = None
    if request.method == 'GET' and request.url.path == '/':
        supplied = request.query_params.get('access_token')
    elif request.method == 'POST' and request.url.path == '/tablet-login':
        form = await request.form()
        supplied = form.get('access_token')
    if supplied is not None:
        if matches(supplied, token):
            response = RedirectResponse('/', status_code=303)
            response.set_cookie(COOKIE_NAME, session_value(token), httponly=True,
                                samesite='lax', max_age=30*24*3600, path='/')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            return response
        return HTMLResponse(LOGIN_PAGE.replace('<h1>', '<p>访问码不正确，请重新输入。</p><h1>', 1),
                            status_code=401, headers={'Cache-Control': 'no-store'})
    if matches(request.cookies.get(COOKIE_NAME), session_value(token)):
        return None
    if request.method == 'GET' and request.url.path == '/':
        return HTMLResponse(LOGIN_PAGE, status_code=401, headers={'Cache-Control': 'no-store'})
    return JSONResponse({'detail': '请先用电脑显示的二维码或访问码连接。'}, status_code=401,
                        headers={'Cache-Control': 'no-store'})
