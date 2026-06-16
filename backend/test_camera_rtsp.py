"""Test RTSP camera at discovered IPs."""
import cv2

cameras = [
    ("192.168.1.3", "rtsp://admin:JLGMKG@192.168.1.3:554/ch1/main"),
    ("192.168.1.3", "rtsp://admin:JLGMKG@192.168.1.3:554/Streaming/Channels/101"),
    ("192.168.1.10", "rtsp://admin:JLGMKG@192.168.1.10:554/ch1/main"),
    ("192.168.1.10", "rtsp://admin:JLGMKG@192.168.1.10:554/Streaming/Channels/101"),
]

print(f"OpenCV: {cv2.__version__}\n")

for ip, url in cameras:
    print(f"Testing: {url}")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if cap.isOpened():
        for _ in range(3):
            cap.grab()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            out = f"C:\\Users\\Admin\\Documents\\camera_{ip.replace('.','_')}.jpg"
            cv2.imwrite(out, frame)
            print(f"  SUCCESS: {w}x{h} saved to {out}\n")
        else:
            print(f"  Opened but no frame\n")
    else:
        cap.release()
        print(f"  Failed to open\n")

print("Done.")
