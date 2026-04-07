"""
Tests para WhatsApp Client (360dialog)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from dental.core.whatsapp_client import (
    WhatsAppClient,
    get_whatsapp_client,
    send_whatsapp,
)


class TestWhatsAppClient:
    """Tests para WhatsAppClient"""

    def test_client_not_configured_without_api_key(self):
        """Sin API key, el cliente está en modo dev"""
        with patch.dict('os.environ', {}, clear=True):
            client = WhatsAppClient(api_key=None)
            assert not client.is_configured

    def test_client_configured_with_api_key(self):
        """Con API key, el cliente está configurado"""
        client = WhatsAppClient(api_key="test_api_key")
        assert client.is_configured

    @pytest.mark.asyncio
    async def test_send_text_dev_mode(self):
        """En modo dev, enviar texto devuelve éxito sin llamar a la API"""
        client = WhatsAppClient(api_key=None)
        result = await client.send_text("+34612345678", "Hola test")
        
        assert result["status"] == "dev_mode"
        assert "message_id" in result

    @pytest.mark.asyncio
    async def test_send_text_normalizes_phone(self):
        """Verifica que el número de teléfono se normaliza"""
        client = WhatsAppClient(api_key="test_key")
        
        # Mock httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "msg_123"}]}
        
        with patch.object(client, '_get_client') as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http
            
            await client.send_text("+34 612 345 678", "Test")
            
            # Verificar que el número se normalizó
            call_args = mock_http.post.call_args
            payload = call_args[1]["json"]
            assert payload["to"] == "34612345678"

    @pytest.mark.asyncio
    async def test_send_text_success(self):
        """Envío exitoso devuelve mensaje ID"""
        client = WhatsAppClient(api_key="test_key")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_123"}]}
        
        with patch.object(client, '_get_client') as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http
            
            result = await client.send_text("+34612345678", "Hola!")
            
            assert result["status"] == "sent"
            assert result["message_id"] == "wamid_123"

    @pytest.mark.asyncio
    async def test_send_text_api_error(self):
        """Error de API devuelve status error"""
        client = WhatsAppClient(api_key="test_key")
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request: Invalid phone number"
        
        with patch.object(client, '_get_client') as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http
            
            result = await client.send_text("+34612345678", "Hola!")
            
            assert result["status"] == "error"
            assert result["error_code"] == 400

    @pytest.mark.asyncio
    async def test_send_text_timeout(self):
        """Timeout devuelve error"""
        client = WhatsAppClient(api_key="test_key")
        
        with patch.object(client, '_get_client') as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_get_client.return_value = mock_http
            
            result = await client.send_text("+34612345678", "Hola!")
            
            assert result["status"] == "error"
            assert "timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_send_template_dev_mode(self):
        """Templates en modo dev"""
        client = WhatsAppClient(api_key=None)
        result = await client.send_template("+34612345678", "appointment_reminder")
        
        assert result["status"] == "dev_mode"
        assert result["template"] == "appointment_reminder"

    @pytest.mark.asyncio
    async def test_mark_as_read_dev_mode(self):
        """Mark as read en modo dev siempre retorna True"""
        client = WhatsAppClient(api_key=None)
        result = await client.mark_as_read("msg_123")
        assert result is True


class TestHelperFunctions:
    """Tests para funciones helper"""

    def test_get_whatsapp_client_singleton(self):
        """get_whatsapp_client devuelve singleton"""
        # Reset singleton
        import dental.core.whatsapp_client as module
        module._client = None
        
        client1 = get_whatsapp_client()
        client2 = get_whatsapp_client()
        
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_send_whatsapp_helper(self):
        """send_whatsapp helper funciona"""
        import dental.core.whatsapp_client as module
        module._client = None
        
        result = await send_whatsapp("+34612345678", "Test", "clinic_001")
        assert result is True  # Dev mode
