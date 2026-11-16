from pathlib import Path
import importlib.util
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.tablet_access import COOKIE_NAME, allowed_hosts, session_value

DATA=Path(__file__).resolve().parents[1]/'app/data'
TOKEN='test-tablet-access-token-with-enough-entropy'


def client(tmp_path,monkeypatch):
    monkeypatch.setenv('JCC_ALLOWED_HOSTS','192.168.50.12')
    monkeypatch.setenv('JCC_LAN_ACCESS_TOKEN',TOKEN)
    return TestClient(create_app(DATA,tmp_path),base_url='http://192.168.50.12:8766')


def test_lan_code_authenticates_then_same_origin_api_works(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    assert c.get('/').status_code==401
    assert c.get('/api/history').status_code==401
    response=c.get('/?access_token='+TOKEN,follow_redirects=False)
    assert response.status_code==303 and response.headers['location']=='/'
    assert TOKEN not in response.headers['set-cookie']
    assert 'HttpOnly'in response.headers['set-cookie'] and 'SameSite=lax'in response.headers['set-cookie']
    assert c.cookies[COOKIE_NAME]==session_value(TOKEN)
    assert c.get('/').status_code==200
    assert c.get('/api/health').status_code==200
    assert c.post('/api/recommend',json=c.get('/api/demo').json(),headers={'Origin':'http://192.168.50.12:8766'}).status_code==200
    assert c.post('/api/model/train',json={'mode':'nature'},headers={'Origin':'http://different.example'}).status_code==403


def test_wrong_code_missing_code_and_untrusted_hosts_do_not_expose_data(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    assert c.get('/?access_token=wrong').status_code==401
    assert c.get('/?access_token=汉字').status_code==401
    assert c.get('/docs').status_code==401
    assert c.get('/api/health',headers={'Host':'untrusted.example'}).status_code==400
    assert c.post('/tablet-login',data={'access_token':TOKEN},headers={'Origin':'http://untrusted.example'}).status_code==403
    assert c.post('/tablet-login',data={'access_token':TOKEN}).status_code==200


def test_default_local_entry_does_not_require_lan_code_or_accept_unknown_host(tmp_path,monkeypatch):
    monkeypatch.delenv('JCC_LAN_ACCESS_TOKEN',raising=False)
    monkeypatch.delenv('JCC_ALLOWED_HOSTS',raising=False)
    c=TestClient(create_app(DATA,tmp_path))
    assert c.get('/api/health').status_code==200
    assert c.get('/api/health',headers={'Host':'192.168.50.12'}).status_code==400
    with pytest.raises(ValueError):allowed_hosts('*')


def test_launcher_selects_physical_rfc1918_address_not_virtual_proxy(monkeypatch):
    path=Path(__file__).resolve().parents[1]/'scripts/tablet_server.py'
    spec=importlib.util.spec_from_file_location('tablet_launcher',path)
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    monkeypatch.delenv('JCC_LAN_IP',raising=False)
    interfaces=[{'ifname':'Meta','addr_info':[{'local':'198.18.0.1','scope':'global'}]},
                {'ifname':'docker0','addr_info':[{'local':'172.17.0.1','scope':'global'}]},
                {'ifname':'eno1','addr_info':[{'local':'10.30.64.139','scope':'global'}]}]
    with patch.object(launcher.subprocess,'run',return_value=type('R',(),{'stdout':json.dumps(interfaces)})()):
        assert launcher.find_lan_ip()=='10.30.64.139'
    monkeypatch.setenv('JCC_LAN_IP','0.0.0.0')
    with pytest.raises(ValueError):launcher.find_lan_ip()
