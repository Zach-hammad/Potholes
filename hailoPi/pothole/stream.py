import cv2
import numpy as np
from hailort import HEF, InferenceRunner

# === Config ===
HEF_PATH = "pothole.hef"
INPUT_WIDTH = 640
INPUT_HEIGHT = 640
CONF_THRESHOLD = 0.4

# === Decode YOLO Output ===
def decode_output(output, img_w, img_h):
    detections = []
    output = output.reshape(-1, 5)  # [x_center, y_center, width, height, conf]

    for det in output:
        x_center, y_center, w, h, conf = det

        if conf > CONF_THRESHOLD:
            x1 = int((x_center - w / 2) * img_w)
            y1 = int((y_center - h / 2) * img_h)
            x2 = int((x_center + w / 2) * img_w)
            y2 = int((y_center + h / 2) * img_h)
            detections.append((x1, y1, x2, y2, conf))

    return detections

# === Main Inference Loop ===
hef = HEF(HEF_PATH)
network_groups = hef.configure()
network_group = network_groups[0]

with InferenceRunner(network_group) as runner:
    input_vstream_info = runner.get_input_vstream_infos()[0]
    output_vstream_info = runner.get_output_vstream_infos()[0]

    with runner.get_vstreams() as (input_vstreams, output_vstreams):
        input_vstream = input_vstreams[0]
        output_vstream = output_vstreams[0]

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("Camera not accessible")

        print("? Starting Pothole Detection... Press 'q' to exit.")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Resize to model input size
            resized = cv2.resize(frame, (INPUT_WIDTH, INPUT_HEIGHT))
            input_data = resized.astype(np.uint8).flatten()

            # Run inference
            input_vstream.send(input_data)
            output_data = output_vstream.receive()

            # Decode detections
            detections = decode_output(output_data, frame.shape[1], frame.shape[0])

            # Draw boxes
            for (x1, y1, x2, y2, conf) in detections:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                label = f"Pothole {conf:.2f}"
                cv2.putText(frame, label, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # Show output
            cv2.imshow("Pothole Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()

