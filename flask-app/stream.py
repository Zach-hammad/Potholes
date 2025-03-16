import cv2
from ultralytics import YOLO  # Ensure you have ultralytics installed (pip install ultralytics)

# Load your YOLOv8 model (update the path to your trained pothole detection model)
model = YOLO(r"C:\Users\zac65\OneDrive\Documents\GitHub\Potholes\best.pt")

# Initialize video capture; '0' usually corresponds to the first connected camera device
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Unable to open video stream.")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: Failed to capture frame.")
        break

    # Run detection on the current frame
    results = model(frame)

    # Generate an annotated frame using the detection results.
    # Note: The API might differ; check your specific YOLOv8 documentation.
    annotated_frame = results[0].plot()

    # Display the annotated frame
    cv2.imshow("Live YOLO Pothole Detection", annotated_frame)

    # Press 'q' to exit the loop
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
