import asyncio
import configparser
import logging
import platform
import ssl
import sys

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer, MediaRelay
from argparse import ArgumentParser
from logging_setting import ColorHandler
from signaling import WebSocketClient
from webserver import WebServer


# Класс для создания webRTC подключения
class WebRTCClient:
    def __init__(self, resolution="640x480"):
        self.pc = None
        self.signaling = None
        self.__video = None
        self.resolution = resolution

    async def connect(self, host, port, turn=None):
        ice_servers = [RTCIceServer('stun:stun.l.google.com:19302')]
        if turn:
            ice_servers.append(turn)
        config = RTCConfiguration(ice_servers)
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
        async def on_connected(_):
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

    async def __get_tracks(self):
        video_options = {"video_size": self.resolution, "framerate": "30"}

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


# режим создания файла концфигурации server.ini
def create_client_config():
    try:
        def print_g(text, **args):
            print(f"\x1b[32m{text}\x1b[0m", **args)

        def input_b(text):
            return input(f"\x1b[34m{text}\x1b[0m")

        config = configparser.ConfigParser()
        print_g("Client configuration tool")
        server = input_b("Enter default websockets server: ")
        port = input_b("Enter default websockets port: ")
        resolution = input_b("Choose cam video resolution (default: 640x480): ")
        if not resolution:
            resolution = "640x480"
        log = input_b("Enable debug log level? (Y/N): ").upper() == "Y"
        config["CONNECTION"] = {"socket_server": server, "socket_port": port}
        config["CAM"] = {"resolution": resolution}
        config["LOG"] = {"enable_debug": str(log)}
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
    parser.add_argument("-r", "--resolution", help="Set cam resolution")
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
        if not config.has_option("CONNECTION", "socket_server"):
            logger.error("Server not specified: use -s parameters or create a configuration "
                         "file with the command: client --configuration")
            sys.exit(1)
        args.server = config.get("CONNECTION", "socket_server")
    if not args.port:
        if not config.has_option("CONNECTION", "socket_port"):
            logger.error("Port not specified: use -p parameters or create a configuration "
                         "file with the command: client --configuration")
            sys.exit(1)
        args.port = config.get("CONNECTION", "socket_port")
    if args.verbose or config.get("LOG", "enable_debug", fallback="false").lower() == "true":
        logger.setLevel(logging.DEBUG)
    if not args.resolution:
        args.resolution = config.get("CAM", "resolution", fallback="640x480")

    turn_server = None
    if config.has_option("TURN", "url"):
        url = config.get("TURN", "url")
        username = config.get("TURN", "username", fallback=None)
        password = config.get("TURN", "password", fallback=None)
        turn_server = RTCIceServer(url, username=username, credential=password)

    logger.debug(f"Parameters: port={args.port}, server={args.server}")

    # Получение сертификата
    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    # Создание соединения
    conn = WebRTCClient(args.resolution)

    try:
        # запуск всех задач
        asyncio.get_event_loop().create_task(conn.connect(args.server, args.port, turn_server))
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # закрытие соединений
        asyncio.get_event_loop().run_until_complete(conn.close_connection())


if __name__ == '__main__':
    logger = logging.getLogger("webrtc")
    logger.setLevel(logging.INFO)
    logger.addHandler(ColorHandler())
    main()
