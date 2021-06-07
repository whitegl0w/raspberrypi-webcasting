import asyncio
import logging
import os
import websockets

from argparse import ArgumentParser
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from websockets.exceptions import ConnectionClosedOK

from general_classes.logging_setting import ColorHandler
from websockets import WebSocketServerProtocol

# настройка логов
logger = logging.getLogger("signaling_server")
logger.setLevel(logging.INFO)
logger.addHandler(ColorHandler())


class WebSocketSignalingServer:
    def __init__(self, port):
        # список подключенных клиентов
        self.clients = set()
        # список сообщений
        self.prev_messages = []
        start_server = websockets.serve(self.__handler, '0.0.0.0', port)
        asyncio.ensure_future(start_server)

    async def __handler(self, websock: WebSocketServerProtocol, _):
        logger.info(f"Connected {websock.remote_address} websockets")
        # авторизация
        # генерация случайной последовательности длиной 128 байт
        key = os.urandom(128)
        # чтение публичного ключа
        with open("../rsa_key.pub", "rb") as key_file:
            public_key = serialization.load_pem_public_key(key_file.read())
        # шифрование последовательности
        encrypted_key = public_key.encrypt(key, padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        # отправка зашифрованной последовательности
        await websock.send(encrypted_key)
        # получение последовательности
        try:
            decrypted_key = await websock.recv()
        except ConnectionClosedOK:
            logger.info(f"Disconnected: {websock.remote_address}")
            return
        # проверка на совпадение
        if key != decrypted_key:
            logger.warning(f"Authentication failed: {websock.remote_address}")
            await websock.close()
            return
        # авторизация успешна, прололжение
        logger.info(f"Authentication succeed: {websock.remote_address}")
        self.clients.add(websock)
        # если до подключения клиента на сервер были переданы какие-то сообщения, то они посылаются ему
        if self.prev_messages:
            await asyncio.wait([asyncio.create_task(websock.send(message)) for message in self.prev_messages])
        try:
            # чтение сообщений от клиента
            async for message in websock:
                self.prev_messages.append(message)
                # отправка полученного сообщения всем кроме отправителя
                receivers = (self.clients - {websock})
                if receivers:
                    await asyncio.wait([asyncio.create_task(client.send(message)) for client in receivers])
        finally:
            # удаление клиента из списка при его отключении и очистка сохраненных сообщений
            self.clients.discard(websock)
            self.prev_messages.clear()

    async def close(self):
        if self.clients:
            await asyncio.wait([asyncio.create_task(client.close()) for client in self.clients])


def main():
    parser = ArgumentParser()
    parser.add_argument("-p", "--port", type=int, help='Server port (default: 8080)')
    args = parser.parse_args()

    if not args.port:
        args.port = os.getenv("PORT", default=8080)

    server = WebSocketSignalingServer(args.port)

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.get_event_loop().run_until_complete(server.close())


if __name__ == '__main__':
    main()
