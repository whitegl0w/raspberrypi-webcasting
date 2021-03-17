from aiortc.contrib.media import MediaPlayer, MediaRelay, MediaRecorder, MediaStreamTrack
from time import sleep
import asyncio
import platform
import sys

def get_tracks():
    video_options = {"video_size": "1280x720", "vcodec": "h264", "b:v": "1800k"}
    audio_options = {"acodec": "libmp3lame", "b:a": "128k", "ar": "44100"}
    audio = MediaPlayer(
                        "anullsrc=channel_layout=stereo:sample_rate=44100",
                        format='lavfi',
                        options=audio_options
                    ).audio

    if platform.system() == "Windows":
        video = MediaPlayer(
                        "video=HP TrueVision HD Camera",
                        format="dshow",
                        options=video_options
                    ).video
    else:
        video = MediaPlayer("/dev/video0", format="v4l2", options=video_options).video

    return audio, video

if __name__ == "__main__":
    if len(sys.argv) > 1:
        trans_key = sys.argv[1]
    else:
        print('The following argument is required: translation-key')
        sys.exit()
    relay = MediaRelay()
    recorder = MediaRecorder(f'rtmp://a.rtmp.youtube.com/live2/{trans_key}', format='flv')
    audio, video = get_tracks()
    recorder.addTrack(audio)
    recorder.addTrack(relay.subscribe(video))
    loop = asyncio.get_event_loop()
    loop.create_task(recorder.start())
    loop.run_forever()
