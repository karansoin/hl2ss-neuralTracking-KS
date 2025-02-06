import hl2ss

HOLOLENS_IP = "192.168.1.40"  # Replace with your actual HoloLens 2 IP
PORT = hl2ss.StreamPort.RM_VLC_LEFTFRONT  # Example: left front grayscale camera

MODE = hl2ss.StreamMode.MODE_0  # Standard mode
WIDTH = 1920                    # Default PV resolution width
HEIGHT = 1080                    # Default PV resolution height
FRAMERATE = 30                   # Default frame rate
DIVISOR = 1                      # No downsampling
PROFILE = hl2ss.VideoProfile.H264_HIGH  # Video encoding
LEVEL = hl2ss.H26xLevel.H264_4_1  # Encoding level
BITRATE = 5_000_000               # Bitrate (5 Mbps)
OPTIONS = {}                      # Empty options
FORMAT = "bgr24"                  # OpenCV-friendly format

# Create the client with all required arguments
client = hl2ss.rx_decoded_pv(HOLOLENS_IP, PORT, hl2ss.ChunkSize.PERSONAL_VIDEO,
                             MODE, WIDTH, HEIGHT, FRAMERATE, DIVISOR, PROFILE,
                             LEVEL, BITRATE, OPTIONS, FORMAT)
client.open()

if client:
    print("✅ Connected to HoloLens 2 Streaming Server!")
else:
    print("❌ Could not connect. Is Unity running?")