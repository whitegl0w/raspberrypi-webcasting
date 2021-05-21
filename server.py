import asyncio
import configparser
import json
import logging
import sys

import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRecorder, MediaRelay
from argparse import ArgumentParser
from logging_setting import ColorHandler
from websockets import WebSocketServerProtocol


class WebSocketServer:
    def __init__(self, port):
        self.__websock = None
        self.__message_event = None
        start_server = websockets.serve(self.__handler__, '0.0.0.0', port)
        asyncio.ensure_future(start_server)

    async def __handler__(self, websock: WebSocketServerProtocol, _):
        logger.info(f"Connected {websock.remote_address} websockets")
        self.__websock = websock
        async for message in websock:
            data = json.loads(message)
            if self.__message_event:
                await self.__message_event(data)

    def on_message(self, fn):
        self.__message_event = fn

    async def send_data(self, data: dict):
        if self.__websock:
            message = json.dumps(data)
            await self.__websock.send(message)

    async def close(self):
        if self.__websock:
            await self.__websock.close()


class WebRTCServer:
    def __init__(self):
        self.pc = None
        self.signaling = None
        self.recorder = None

    async def accept(self, port):
        relay = MediaRelay()
        config = RTCConfiguration([RTCIceServer('stun:stun.l.google.com:19302')])
        self.pc = RTCPeerConnection(config)
        self.signaling = WebSocketServer(port)
        self.recorder = MediaRecorder('video/out-%3d.mp4',
                                      format="segment",
                                      options={"segment_time": "00:00:20", "reset_timestamps": "1"})

        @self.signaling.on_message
        async def on_message(message):
            logger.debug(f"{message.get('type')} received")
            if message.get("type") == "offer":
                offer = RTCSessionDescription(sdp=message["sdp"], type=message["type"])
                await self.pc.setRemoteDescription(offer)
                answer = await self.pc.createAnswer()
                await self.pc.setLocalDescription(answer)
                answer = {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}
                logger.debug("Answer sent")
                await self.signaling.send_data(answer)

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
                self.recorder.addTrack(relay.subscribe(track))
            logger.info(f"Track {track.kind} added")

            @track.on("ended")
            async def on_ended():
                await self.recorder.stop()
                logger.info(f"Track {track.kind} ended")

    async def close_connection(self):
        await self.recorder.stop()
        await self.signaling.close()
        await self.pc.close()


def create_server_config():
    try:
        def print_g(text, **args):
            print(f"\x1b[32m{text}\x1b[0m", **args)

        def print_b(text, **args):
            print(f"\x1b[34m{text}\x1b[0m", **args)

        config = configparser.ConfigParser()
        print_g("Server configuration tool")
        print_b("Enter default websockets port: ", end="")
        port = input()
        print_b("Enter the duration of one fragment of the video file (hh:mm:ss): ", end="")
        segment = input()
        config["CONNECTION"] = {"Port": port}
        config["RECORDER"] = {"Segment_time": segment}
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
    parser.add_argument("-s", "--segment", help="Set the duration of one fragment of the video file")
    parser.add_argument("-c", "--configuration", action="count", help="Create config file")
    args = parser.parse_args()
    # Режим создания конфигурации
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
        args.segment = config.get("CONNECTION", "Segment_time", fallback="00:30:00")
    if args.verbose or config.has_option("LOG", "Debug"):
        logger.setLevel(logging.DEBUG)

    # Создание подключения
    conn = WebRTCServer()
    try:
        asyncio.get_event_loop().create_task(conn.accept(args.port))
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.get_event_loop().run_until_complete(conn.close_connection())


if __name__ == '__main__':
    # Настройка логов
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.addHandler(ColorHandler())
    main()
