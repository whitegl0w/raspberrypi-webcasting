# Video Webcasting System
The program captures video from the camera and transfers it to a remote server using WebRTC technology. The server saves the video to the drive and retransmits it to the connected HTTP clients 

## Usage
#### Start recording video on the Raspberry Pi and transferring it to the web-server
    python client.py [-p OPEN_PORT] [-r VIDEO_RESOLUTION] [-b VIDEO_BITRATE] [--cert-file CERT_FILE] [--key-file KEY_FILE]
##### For more help on the options available, run:
    python client.py -h

#### Run web-server for receiving video
    python server.py [-s SERVER_IP] [-p SERVER_PORT] [-st SEGMENT_DURATION] [--cert-file CERT_FILE] [--key-file KEY_FILE]
##### For more help on the options available, run:
    python server.py -h
    
### Save configuration
##### Instead of setting parameters each time you start, you can create a configuration file. To create it, run the commands:
    python server.py -c
    python client.py -c
    
