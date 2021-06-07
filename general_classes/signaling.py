import asyncio
import json
import logging
import websockets

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from general_classes.logging_setting import ColorHandler
from websockets import WebSocketServerProtocol


# настройка логов
logger = logging.getLogger("socket")
logger.setLevel(logging.INFO)
logger.addHandler(ColorHandler())


# базовый класс для дальнейшего наследования
class WebSocketBasic:
    def __init__(self):
        self._websock = None
        self._on_message = None
        self._on_connected = None

    def on_message(self, fn):
        self._on_message = fn

    def on_connected(self, fn):
        self._on_connected = fn

    async def send_data(self, data: dict):
        if self._websock:
            message = json.dumps(data)
            await self._websock.send(message)

    async def close(self):
        if self._websock:
            await self._websock.close()


# Класс для создания сигнального канала
class WebSocketServer(WebSocketBasic):
    def __init__(self, port):
        super().__init__()
        start_server = websockets.serve(self.__handler, '0.0.0.0', port)
        asyncio.ensure_future(start_server)

    async def __handler(self, websock: WebSocketServerProtocol, _):
        logger.info(f"Connected {websock.remote_address} websockets")
        if self._on_connected:
            await self._on_connected(websock)
        self._websock = websock
        async for message in websock:
            data = json.loads(message)
            if self._on_message:
                await self._on_message(data)


# Класс для создания сигнального канала
class WebSocketClient(WebSocketBasic):
    def __init__(self, server, port):
        super().__init__()
        uri = f"wss://{server}:{port}"
        asyncio.get_event_loop().create_task(self.__connect(uri))

    async def __connect(self, uri):
        async with websockets.connect(uri, ssl=True) as self._websock:
            logger.info(f"Connected {self._websock.remote_address} websockets")
            # авторизация
            with open("rsa_key", "rb") as key_file:
                private_key = serialization.load_pem_private_key(key_file.read(), password=None)
            encrypted_key = await self._websock.recv()
            try:
                decrypted_key = private_key.decrypt(encrypted_key, padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
            except ValueError:
                logger.error(f"Authentication failed")
                await self._websock.close()
                return
            await self._websock.send(decrypted_key)
            # продолжение работы
            logger.info(f"Authentication succeed")
            if self._on_connected:
                await self._on_connected(self._websock)
            async for message in self._websock:
                data = json.loads(message)
                if self._on_message:
                    await self._on_message(data)
