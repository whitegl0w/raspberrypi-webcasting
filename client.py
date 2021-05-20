import asyncio
import json
import logging
import platform
import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer, MediaRelay
from argparse import ArgumentParser


class WebSocketClient:
    def __init__(self, server, port):
        self.__websock = None
        self.__message_event = None
        uri = f"ws://{server}:{port}"
        asyncio.get_event_loop().create_task(self.__connect__(uri))

    async def __connect__(self, uri):
        async with websockets.connect(uri) as self.__websock:
            logger.info(f"Connected {self.__websock.remote_address} websockets")
            async for message in self.__websock:
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


class WebRTCClient:
    def __init__(self):
        self.pc = None
        self.signaling = None
        self.video = None

    async def connect(self, host, port):
        relay = MediaRelay()
        config = RTCConfiguration([RTCIceServer('stun:stun.l.google.com:19302')])
        self.pc = RTCPeerConnection(config)
        self.signaling = WebSocketClient(host, port)
        self.video = await self.__get_tracks__()
        self.pc.addTrack(relay.subscribe(self.video))

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
            logger.info(f"Connection {self.pc.connectionState}")

        async def send_offer():
            logger.debug(f"Ice Gathering State: {self.pc.iceGatheringState}")
            if self.pc.iceGatheringState == 'complete':
                logger.debug("Offer sent")
                await self.signaling.send_data(
                    {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}
                )
            else:
                self.pc.once("icegatheringstatechange", send_offer)

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        await send_offer()

    @staticmethod
    async def __get_tracks__():
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
        if self.pc and self.video and self.signaling:
            await self.pc.close()
            self.video.stop()
            await self.signaling.close()


class CustomFilter(logging.Filter):
    COLOR = {
        "DEBUG": "GREEN",
        "INFO": "GREEN",
        "WARNING": "YELLOW",
        "ERROR": "RED",
        "CRITICAL": "RED",
    }

    def filter(self, record):
        record.color = CustomFilter.COLOR[record.levelname]
        return True


def main():
    parser = ArgumentParser()
    parser.add_argument("host", help='Server IP address')
    parser.add_argument("port", type=int, help='Server port')
    parser.add_argument("-v", "--verbose", action="count", help='Enable debug log')
    args = parser.parse_args()
    conn = WebRTCClient()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        asyncio.get_event_loop().create_task(conn.connect(args.host, args.port))
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.get_event_loop().run_until_complete(conn.close_connection())


if __name__ == '__main__':
    logging.basicConfig(
        format="[%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.addFilter(CustomFilter())
    main()
