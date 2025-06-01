import cv2
import hailo_platform as hpf
import numpy as np
from picamera2 import Picamera2

# Initialize Picamera2
picam2 = Picamera2()
picam2.preview_configuration.main.size = (1280, 720)
picam2.preview_configuration.main.format = "RGB888"
picam2.preview_configuration.align()
picam2.configure("preview")
picam2.start()

# Load the compiled HEF model
hef = hpf.HEF("yolov5_model.hef")

# Initialize the Hailo runtime
with hpf.VDevice() as target:
    # Configure the device with the HEF
    configure_params = hpf.ConfigureParams.create_from_hef(hef, interface=hpf.HailoStreamInterface.PCIe)
    network_group = target.configure(hef, configure_params)[0]
    network_group_params = network_group.create_params()

    while True:
        # Capture frame-by-frame
        frame = picam2.capture_array()

        # Preprocess the frame (resize and normalize)
        input_tensor = cv2.resize(frame, (640, 640))
        input_tensor = np.transpose(input_tensor, (2, 0, 1))  # HWC to CHW
        input_tensor = np.expand_dims(input_tensor, axis=0).astype(np.float32)

        # Run inference
        output = network_group.execute(input_tensor)

        # Post-process the output to extract bounding boxes and labels
        # (Implement according to your model's output format)

        # Visualize the results
        for detection in output:
            # Draw bounding boxes and labels on the frame
            pass

        # Display the resulting frame
        cv2.imshow("Camera", frame)

        # Break the loop if 'q' is pressed
        if cv2.waitKey(1) == ord("q"):
            break

# Release resources and close windows
cv2.destroyAllWindows()
