import cv2
from ultralytics import YOLO  # Ensure you have ultralytics installed (pip install ultralytics)
from picamera2 import Picamera2
from picamera2.array import PiRGBArray
import time
# Load your YOLOv8 model (update the path to your trained pothole detection model)
model = YOLO(r"best.pt")

# Initialize video capture; '0' usually corresponds to the first connected camera device
#cap = cv2.VideoCapture()
#picam2 = Picamera2()
#cap = cv2.VideoCapture('0')

camera = Picamera2()
camera.resolution = (640, 480)
camera.framerate = 32
rawCapture = PiRGBArray(camera, size=(640, 480))
# allow the camera to warmup
time.sleep(0.1)
# capture frames from the camera
#for frame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
#rawCapture = PiRGBArray(cam)
#time.sleep(0.2)

# capture frames from the camera
for frame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
	# grab the raw NumPy array representing the image, then initialize the timestamp
	# and occupied/unoccupied text
	image = frame.array
	# show the frame
	cv2.imshow("Frame", image)
	key = cv2.waitKey(1) & 0xFF
	# clear the stream in preparation for the next frame
	rawCapture.truncate(0)
	# if the `q` key was pressed, break from the loop
	if key == ord("q"):
		break


#if not cap.isOpened():
#    print("Error: Unable to open video stream.")
#    exit()#

#while True:
#    ret, frame = cap.read()
#    if not ret:
#        print("Error: Failed to capture frame.")
#        break

    # Run detection on the current frame
#    results = model(frame)

    # Generate an annotated frame using the detection results.
    # Note: The API might differ; check your specific YOLOv8 documentation.
#    annotated_frame = results[0].plot()

    # Display the annotated frame
#    cv2.imshow("Live YOLO Pothole Detection", annotated_frame)

    # Press 'q' to exit the loop
#    if cv2.waitKey(1) & 0xFF == ord('q'):
#        break

#cap.release()
#cv2.destroyAllWindows()
