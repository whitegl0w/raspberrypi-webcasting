import asyncio
import configparser
import json
import logging
import platform
import ssl
import sys
import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer, MediaRelay
from argparse import ArgumentParser
from logging_setting import ColorHandler
from webserver import WebServer


class WebSocketClient:
    def __init__(self, server, port):
        self.__websock = None
        self.__on_message = None
        self.__on_connected = None
        uri = f"ws://{server}:{port}"
        asyncio.get_event_loop().create_task(self.__connect(uri))

    async def __connect(self, uri):
        async with websockets.connect(uri) as self.__websock:
            logger.info(f"Connected {self.__websock.remote_address} websockets")
            if self.__on_connected:
                await self.__on_connected()
            async for message in self.__websock:
                data = json.loads(message)
                if self.__on_message:
                    await self.__on_message(data)

    def on_message(self, fn):
        self.__on_message = fn

    def on_connected(self, fn):
        self.__on_connected = fn

    async def send_data(self, data: dict):
        if self.__websock:
            message = json.dumps(data)
            await self.__websock.send(message)

    async def close(self):
        if self.__websock:
            await self.__websock.close()


class WebRTCClient:
    def __init__(self):
        self.pc = None
        self.signaling = None
        self.__video = None

    async def connect(self, host, port):
        config = RTCConfiguration([RTCIceServer('stun:stun.l.google.com:19302')])
        self.pc = RTCPeerConnection(config)

        if not self.__video:
            self.__video = await self.__get_tracks()
        self.pc.addTrack(MediaRelay().subscribe(self.__video))

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        self.signaling = WebSocketClient(host, port)

        async def send_offer():
            logger.debug(f"Ice Gathering State: {self.pc.iceGatheringState}")
            if self.pc.iceGatheringState == 'complete':
                logger.debug("Offer sent")
                await self.signaling.send_data(
                    {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}
                )
            else:
                self.pc.once("icegatheringstatechange", send_offer)

        @self.signaling.on_connected
        async def on_connected():
            await send_offer()

        @self.signaling.on_message
        async def on_message(message):
            logger.debug(f"{message.get('type')} received")
            if message.get("type") == "answer":
                answer = RTCSessionDescription(sdp=message["sdp"], type=message["type"])
                await self.pc.setRemoteDescription(answer)

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self.pc.connectionState == "failed":
                await self.pc.close()
            logger.info(f"Connection state: {self.pc.connectionState}")

    @staticmethod
    async def __get_tracks():
        video_options = {"video_size": "640x480", "framerate": "30"}

        if platform.system() == "Windows":
            video_track = MediaPlayer(
                "video=HP TrueVision HD Camera",
                format="dshow",
                options=video_options
            ).video
        else:
            video_track = MediaPlayer("/dev/video0", format="v4l2", options=video_options).video

        return video_track

    async def close_connection(self):
        if self.pc and self.__video and self.signaling:
            self.__video.stop()
            await self.pc.close()
            await self.signaling.close()

    async def video_track(self):
        if not self.__video:
            self.__video = await self.__get_tracks()
        return MediaRelay().subscribe(self.__video)


def create_client_config():
    try:
        def print_g(text, **args):
            print(f"\x1b[32m{text}\x1b[0m", **args)

        def print_b(text, **args):
            print(f"\x1b[34m{text}\x1b[0m", **args)

        config = configparser.ConfigParser()
        print_g("Client configuration tool")
        print_b("Enter default websockets server: ", end="")
        server = input()
        print_b("Enter default websockets port: ", end="")
        port = input()
        config["CONNECTION"] = {"Server": server, "Port": port}
        with open('client.ini', 'w', encoding="utf-8") as configfile:
            config.write(configfile)
        print_g("Config client.ini created\n")
    except KeyboardInterrupt:
        pass


def main():
    # Парсинг аргументов
    parser = ArgumentParser()
    parser.add_argument("-s", "--server", help='Server IP address')
    parser.add_argument("-p", "--port", type=int, help='Server port')
    parser.add_argument("-v", "--verbose", action="count", help='Enable debug log')
    parser.add_argument("-c", "--configuration", action="count", help="Create config file")
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    args = parser.parse_args()
    # Режим создания конфигурации
    if args.configuration:
        create_client_config()
        sys.exit(0)
    # Получение конфига
    config = configparser.ConfigParser()
    config.read('client.ini')
    # Настройка параметров
    if not args.server:
        if not config.has_option("CONNECTION", "Server"):
            logger.error("Server not specified: use -s parameters or create a configuration "
                         "file with the command: client --configuration")
            sys.exit(1)
        args.server = config.get("CONNECTION", "Server")
    if not args.port:
        if not config.has_option("CONNECTION", "Port"):
            logger.error("Port not specified: use -p parameters or create a configuration "
                         "file with the command: client --configuration")
            sys.exit(1)
        args.port = config.get("CONNECTION", "Port")
    if args.verbose or config.has_option("LOG", "Debug"):
        logger.setLevel(logging.DEBUG)
    logger.debug(f"Parameters: port={args.port}, server={args.server}")

    # Получение сертификата
    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    # Создание веб-сервера
    conn = WebRTCClient()
    web_server = WebServer(conn.video_track, ssl_context)
    # запуск
    try:
        asyncio.get_event_loop().create_task(web_server.start_webserver())
        asyncio.get_event_loop().create_task(conn.connect(args.server, args.port))
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.get_event_loop().run_until_complete(conn.close_connection())


if __name__ == '__main__':
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.addHandler(ColorHandler())
    main()
