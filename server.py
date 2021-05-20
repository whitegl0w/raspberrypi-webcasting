import asyncio
import json
import logging

import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRecorder, MediaRelay
from argparse import ArgumentParser
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
            logger.info(f"Connection {self.pc.connectionState}")

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
    parser.add_argument("-p", "--port", type=int, help='Server port (default: 443)')
    parser.add_argument("-v", "--verbose", action="count", help='Enable debug log')
    args = parser.parse_args()
    if not args.port:
        args.port = 443
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    conn = WebRTCServer()

    try:
        asyncio.get_event_loop().create_task(conn.accept(args.port))
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
