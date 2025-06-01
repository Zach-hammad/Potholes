import os
import json
import cv2

def convert_bbox_to_yolo(bbox):
    x_center = (bbox["xmin"] + bbox["xmax"]) / 2
    y_center = (bbox["ymin"] + bbox["ymax"]) / 2
    width = bbox["xmax"] - bbox["xmin"]
    height = bbox["ymax"] - bbox["ymin"]
    return x_center, y_center, width, height

def process_directory(input_dir, image_ext="_best.jpg"):
    for filename in os.listdir(input_dir):
        if filename.endswith(".json"):
            json_path = os.path.join(input_dir, filename)
            base_name = os.path.splitext(filename)[0]
            image_path = os.path.join(input_dir, f"{base_name}{image_ext}")
            output_txt = os.path.join(input_dir, f"{base_name}.txt")

            if not os.path.exists(image_path):
                print(f"[SKIP] Image not found for {filename}")
                continue

            # Load image for dimension check (optional if bbox coords are normalized)
            img = cv2.imread(image_path)
            if img is None:
                print(f"[SKIP] Failed to read image: {image_path}")
                continue

            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                bboxes = data.get("bboxes", [])

                with open(output_txt, 'w') as out_file:
                    for bbox in bboxes:
                        class_id = bbox["class_id"]  # use 1 for pothole, 2 for manhole if needed
                        x_center, y_center, width, height = convert_bbox_to_yolo(bbox)
                        out_file.write(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")

                print(f"[OK] Wrote YOLO label: {output_txt}")

            except Exception as e:
                print(f"[ERROR] {filename}: {e}")

if __name__ == "__main__":
    input_dir = "E:\Downloads\pothole_files"
    process_directory(input_dir)
