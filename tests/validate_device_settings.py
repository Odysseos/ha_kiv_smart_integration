# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the standalone HTTP server without contacting a physical device."""
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/vakio_kiv_local/www/vakio_settings.html'


def main():
    text = SOURCE.read_text()
    code = text.split('<!-- LOCAL_SERVER_BEGIN\n', 1)[1].split('\nLOCAL_SERVER_END -->', 1)[0]
    previous = sys.argv
    try:
        sys.argv = ['settings-test', str(SOURCE)]
        namespace = {'__name__': 'settings_test'}
        exec(compile(code, str(SOURCE), 'exec'), namespace)
    finally:
        sys.argv = previous
    calls = []
    scenario = {'status': 200, 'body': b'<html>firmware form</html>', 'error': None}

    class DeviceConnection:
        def __init__(self, host, port, timeout):
            self.host = host
            assert port == 80 and timeout == 12

        def request(self, method, path, body=None, headers=None):
            calls.append((self.host, method, path, body, headers))
            if scenario['error']:
                raise scenario['error']

        def getresponse(self):
            return SimpleNamespace(status=scenario['status'], reason='test',
                                   read=lambda limit: scenario['body'][:limit])

        def close(self):
            pass

    namespace['http'] = SimpleNamespace(client=SimpleNamespace(
        HTTPConnection=DeviceConnection, HTTPException=http.client.HTTPException))
    server = namespace['ThreadingHTTPServer'](('127.0.0.1', 0), namespace['Handler'])
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    token = namespace['TOKEN']
    host = f'127.0.0.1:{server.server_port}'

    def request(path, method='GET', data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request(method, path, body=data, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    try:
        status, body, headers = request('/')
        assert status == 200 and token.encode() in body
        assert b"const TOKEN = '__LOCAL_TOKEN__'" not in body
        assert headers['Cache-Control'] == 'no-store'
        assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
        assert not calls
        auth = {'X-Local-Token': token}
        path = '/api/device?ip=192.168.1.100'
        status, body, _ = request(path, headers=auth)
        assert status == 200 and json.loads(body)['html'] == '<html>firmware form</html>'
        assert calls[-1][:3] == ('192.168.1.100', 'GET', '/')
        payload = {'SSID': 'Сеть', 'MQTTNAME': '192.168.1.10', 'APTIME': '0',
                   'MQTTPASSWORD': 'test-password'}
        status, body, _ = request(path, 'POST', json.dumps(payload), auth)
        assert status == 200 and json.loads(body)['status'] == 200
        address, method, endpoint, raw, forwarded_headers = calls[-1]
        assert (address, method, endpoint) == ('192.168.1.100', 'POST', '/newdata')
        assert json.loads(raw) == payload
        assert forwarded_headers['Content-Type'] == 'text/plain;charset=UTF-8'
        assert b'test-password' not in body
        before = len(calls)
        for path_, extra in [
            (path, {'Host': 'wrong-host'}),
            (path, {'Origin': 'http://example.org'}),
            (path, {'X-Local-Token': 'wrong-token'}),
        ]:
            status, _, _ = request(path_, headers={**auth, **extra})
            assert status == 403
        status, _, _ = request(path)
        assert status == 403
        for address in ('127.0.0.1', '8.8.8.8', 'example.org', '192.168.1.100&ip=192.168.1.101'):
            status, _, _ = request('/api/device?ip=' + address, headers=auth)
            assert status == 400
        for invalid in ({'unknown': 'value'}, {'SSID': 123}, {'reset': 'off'}, {}):
            status, _, _ = request(path, 'POST', json.dumps(invalid), auth)
            assert status == 400
        status, _, _ = request(path, 'POST', 'not-json', auth)
        assert status == 400
        status, _, _ = request(path, 'POST', 'x' * 16385, auth)
        assert status == 400
        assert len(calls) == before
        scenario['error'] = socket.timeout()
        status, body, _ = request(path, 'POST', json.dumps(payload), auth)
        assert status == 504 and 'неизвестен' in json.loads(body)['error']
        assert len(calls) == before + 1  # No automatic POST retry.
        scenario['error'] = None
        scenario['status'] = 500
        status, body, _ = request(path, headers=auth)
        assert status == 200 and json.loads(body)['status'] == 500
        scenario['status'] = 200
        scenario['body'] = b'x' * 1048577
        status, _, _ = request(path, headers=auth)
        assert status == 502
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    print('PASS: loopback server; session token; GET/POST to chosen device; JSON and APTIME preserved; blocked foreign requests; timeout without repeat writes; HTTP errors; response size limit')


if __name__ == '__main__':
    main()
