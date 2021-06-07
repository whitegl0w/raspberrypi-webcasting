import asyncio
import configparser
import logging
import ssl
import sys

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, MediaStreamTrack
from aiortc.contrib.media import MediaRecorder, MediaRelay
from argparse import ArgumentParser
from general_classes.logging_setting import ColorHandler
from general_classes.signaling import WebSocketServer, WebSocketClient
from web_server.webserver import WebServer


# исправление pts-presentation timestamp в видео на равномерный,
# чтобы избежить проблем при кодировании
class FixedPtsTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, track):
        super().__init__()
        self.track = track
        self.pts = 0

    async def recv(self):
        frame = await self.track.recv()
        frame.pts = self.pts
        self.pts += 6122
        return frame


# Класс для создания webRTC подключения
class WebRTCServer:
    def __init__(self):
        self.pc = None
        self.signaling = None
        self.recorder = None
        self.__video = None

    async def accept(self, port, segment_time, server=None, turn=None):
        ice_servers = [RTCIceServer('stun:stun.l.google.com:19302')]
        if turn:
            ice_servers.append(turn)
        config = RTCConfiguration(ice_servers)
        self.pc = RTCPeerConnection(config)
        if server:
            self.signaling = WebSocketClient(server, port)
        else:
            self.signaling = WebSocketServer(port)

        recorder_options = {
            "segment_time": segment_time,
            "reset_timestamps": "1",
            "strftime": "1",
        }
        self.recorder = MediaRecorder('video/%Y-%m-%d_%H-%M-%S.mkv',
                                      format="segment",
                                      options=recorder_options)

        async def send_answer():
            logger.debug(f"Ice Gathering State: {self.pc.iceGatheringState}")
            # отправка происходит если были собраны все IceCandidate
            if self.pc.iceGatheringState == 'complete':
                logger.debug("Answer sent")
                await self.signaling.send_data(
                    {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}
                )
            else:
                # если IceCandidate не собраны, то ожидается их сбор
                self.pc.once("icegatheringstatechange", send_answer)

        @self.signaling.on_message
        async def on_message(message):
            logger.debug(f"{message.get('type')} received")
            if message.get("type") == "offer":
                offer = RTCSessionDescription(sdp=message["sdp"], type=message["type"])
                await self.pc.setRemoteDescription(offer)
                answer = await self.pc.createAnswer()
                await self.pc.setLocalDescription(answer)
                await send_answer()

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self.pc.connectionState == "failed":
                await self.pc.close()
            elif self.pc.connectionState == "connected":
                await self.recorder.start()
            elif self.pc.connectionState == "closed":
                await self.recorder.stop()
                logger.info("Recorder closed")
            logger.info(f"Connection state: {self.pc.connectionState}")

        @self.pc.on("track")
        async def on_track(track):
            if track.kind == "audio":
                self.recorder.addTrack(track)
            elif track.kind == "video":
                self.__video = track
                self.recorder.addTrack(FixedPtsTrack(MediaRelay().subscribe(track)))
            logger.info(f"Track {track.kind} added")

            @track.on("ended")
            async def on_ended():
                await self.recorder.stop()
                logger.info(f"Track {track.kind} ended")

    async def close_connection(self):
        await self.recorder.stop()
        await self.signaling.close()
        await self.pc.close()

    async def video_track(self):
        if self.__video:
            return MediaRelay().subscribe(self.__video)
        else:
            return None


# режим создания файла концфигурации server.ini
def create_server_config():
    try:
        def print_g(text, **args):
            print(f"\x1b[32m{text}\x1b[0m", **args)

        def input_b(text):
            return input(f"\x1b[34m{text}\x1b[0m")

        config = configparser.ConfigParser()
        print_g("Server configuration tool")
        port = input_b("Enter default websockets port: ")
        web = input_b("Enable web server? (Y/N): ").upper() == "Y"
        segment = input_b("Enter the duration of one fragment of the video file (hh:mm:ss): ")
        log = input_b("Enable debug log level? (Y/N): ").upper() == "Y"
        config["CONNECTION"] = {"socket_port": port, "enable_webserver": str(web)}
        config["RECORDER"] = {"segment": segment}
        config["LOG"] = {"enable_debug": str(log)}
        with open('server.ini', 'w', encoding="utf-8") as configfile:
            config.write(configfile)
        print_g("Config server.ini created\n")
    except KeyboardInterrupt:
        pass


def main():
    # Парсинг аргументов
    parser = ArgumentParser()
    parser.add_argument("-p", "--port", type=int, help='Server port (default: 443)')
    parser.add_argument("-v", "--verbose", action="count", help='Enable debug log')
    parser.add_argument("-st", "--segment", help="Set the duration of one fragment of the video file")
    parser.add_argument("-c", "--configuration", action="count", help="Create config file")
    parser.add_argument("-w", "--enableeweb", action="count", help="Enable web server")
    parser.add_argument("-s", "--server", help="Signaling server IP address")
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    args = parser.parse_args()
    # Вход в режим создания конфигурации
    if args.configuration:
        create_server_config()
        sys.exit(0)
    # Получение конфига
    config = configparser.ConfigParser()
    config.read('server.ini')
    # Настройка параметров
    if not args.port:
        args.port = config.get("CONNECTION", "Port", fallback="443")
    if not args.segment:
        args.segment = config.get("RECORDER", "Segment", fallback="00:30:00")
    if args.verbose or config.get("LOG", "enable_debug", fallback="false").lower() == "true":
        logger.setLevel(logging.DEBUG)
    if not args.enableeweb:
        args.enableeweb = config.get("CONNECTION", "enable_webserver", fallback="false").lower() == "true"
    if not args.server:
        args.server = config.get("CONNECTION", "signaling_server", fallback=None)

    turn_server = None
    if config.has_option("TURN", "url"):
        url = config.get("TURN", "url")
        username = config.get("TURN", "username", fallback=None)
        password = config.get("TURN", "password", fallback=None)
        turn_server = RTCIceServer(url, username=username, credential=password)

    logger.debug(f"Parameters: port={args.port}, segment={args.segment}")
    # Получение сертификата
    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    # Создание WebRTC и Web сервера
    conn = WebRTCServer()
    web_server = WebServer(conn.video_track, ssl_context)

    try:
        # запуск всех задач
        if args.enableeweb:
            asyncio.get_event_loop().create_task(web_server.start_webserver())
        asyncio.get_event_loop().create_task(conn.accept(args.port, args.segment, args.server, turn_server))
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # закрытие всех соединений
        task = asyncio.gather(conn.close_connection(), web_server.stop_webserver())
        asyncio.get_event_loop().run_until_complete(task)


if __name__ == '__main__':
    # Настройка логов
    logger = logging.getLogger("webrtc")
    logger.setLevel(logging.INFO)
    logger.addHandler(ColorHandler())
    main()
