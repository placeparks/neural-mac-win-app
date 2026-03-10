import pytest
import socket
from neuralclaw.cortex.action.network import validate_url, validate_url_with_dns

def test_validate_url_allowed():
    result = validate_url("https://example.com/api/data")
    assert result.allowed
    assert result.url == "https://example.com/api/data"

def test_validate_url_blocked_localhost():
    result = validate_url("http://localhost:8080/admin")
    assert not result.allowed
    assert "localhost" in result.reason

def test_validate_url_blocked_private_ip():
    result = validate_url("http://192.168.1.1/router")
    assert not result.allowed
    assert "private" in result.reason

def test_validate_url_blocked_metadata():
    result = validate_url("http://169.254.169.254/latest/meta-data")
    assert not result.allowed
    assert "private" in result.reason or "metadata" in result.reason

def test_validate_url_non_http():
    result = validate_url("file:///etc/passwd")
    assert not result.allowed
    assert "scheme" in result.reason

@pytest.mark.asyncio
async def test_validate_url_with_dns_rebinding(monkeypatch):
    # Mock DNS resolution to return a private IP
    def mock_getaddrinfo(*args, **kwargs):
        # Format: (family, type, proto, canonname, sockaddr)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 80))]
    
    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    
    # "safe.com" resolves to 10.0.0.1 via mock
    result = await validate_url_with_dns("http://safe.com/data")
    assert not result.allowed
    assert "rebinding" in result.reason
