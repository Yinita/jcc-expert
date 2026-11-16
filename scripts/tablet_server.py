#!/usr/bin/env python3
"""Start an access-code protected entry on one physical private IPv4 interface."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=[ipaddress.ip_network(n) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']]


def find_lan_ip():
    requested=os.environ.get('JCC_LAN_IP')
    if requested:
        address=ipaddress.ip_address(requested)
        if address.version!=4 or not any(address in n for n in PRIVATE):
            raise ValueError('JCC_LAN_IP needs a private IPv4 address on this computer')
        return str(address)
    result=subprocess.run(['ip','-j','-4','addr','show','up'],capture_output=True,text=True,check=True)
    for interface in json.loads(result.stdout):
        if interface['ifname'].lower().startswith(('lo','docker','br-','veth','virbr','tun','tap','meta','wg')):
            continue
        for entry in interface.get('addr_info',[]):
            address=ipaddress.ip_address(entry['local'])
            if entry.get('scope')=='global' and any(address in n for n in PRIVATE):
                return str(address)
    raise ValueError('No physical private IPv4 address found; set JCC_LAN_IP explicitly')


def private_file(path,text):
    path.write_text(text,encoding='utf-8')
    path.chmod(0o600)


def main():
    os.chdir(ROOT)
    address=find_lan_ip()
    port=int(os.environ.get('JCC_TABLET_PORT','8766'))
    if not 1024<=port<=65535:
        raise ValueError('JCC_TABLET_PORT must be between 1024 and 65535')
    var=Path(os.environ.get('JCC_VAR_DIR',ROOT/'var')).resolve()
    var.mkdir(parents=True,exist_ok=True)
    token_file=var/'tablet-access-token'
    token=token_file.read_text().strip() if token_file.is_file() else secrets.token_urlsafe(24)
    if len(token)<24:
        raise ValueError('Invalid saved tablet access token; remove it to generate a new one')
    private_file(token_file,token+'\n')
    url=f'http://{address}:{port}/?access_token={token}'
    qr_path=var/'tablet-access.png'
    sys.path.insert(0,str(ROOT/'var/tablet_dependencies'))
    qr_created=False
    try:
        import qrcode
        qrcode.make(url).save(qr_path)
        qr_path.chmod(0o600)
        qr_created=True
    except ImportError:
        print('二维码可选依赖未安装；可使用下面的完整链接。',flush=True)
    private_file(var/'tablet-connection.json',json.dumps({'address':address,'port':port,'url':url,
                'access_token':token,'qr_path':str(qr_path)if qr_created else None},ensure_ascii=False,indent=2))
    print(f'平板入口：{url}\n访问码：{token}',flush=True)
    if qr_created:print(f'二维码：{qr_path}',flush=True)
    print('让平板与电脑处于可互通的同一局域网；电脑保持开机。Ctrl+C关闭此入口。',flush=True)
    os.environ['JCC_ALLOWED_HOSTS']=address
    os.environ['JCC_LAN_ACCESS_TOKEN']=token
    # Do not write the access-code URL into HTTP access logs.
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','app.main:app','--host',address,
                            '--port',str(port),'--no-access-log'])


if __name__=='__main__':
    main()
