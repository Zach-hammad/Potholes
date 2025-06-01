import os
import cv2
from ultralytics import YOLO
import torch

def resize_all_images_in_folder(folder_path, size=(640, 640)):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(('.jpg', '.jpeg', '.png')):
                img_path = os.path.join(root, file)
                img = cv2.imread(img_path)
                if img is not None:
                    resized = cv2.resize(img, size)
                    cv2.imwrite(img_path, resized)

def train_yolo_multi_class(
    data_path,
    weights='yolo11n.pt',
    epochs=350,
    batch_size=64,
    imgsz=640,
    device='0'
):
    # Resize images
    resize_all_images_in_folder(os.path.join(data_path, 'train/images'))
    resize_all_images_in_folder(os.path.join(data_path, 'val/images'))

    # Load model — class count comes from the .yaml
    model = YOLO(weights)

    # Train (head will be reshaped internally based on yaml nc)
    model.train(
        data=os.path.join(data_path, 'dataAug.yaml'),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch_size,
        device=device
    )

if __name__ == "__main__":
    print("Is CUDA available:", torch.cuda.is_available())
    print("Number of GPUs:", torch.cuda.device_count())
    print("CUDA Device Name:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU")
    train_yolo_multi_class(
        data_path="E:/Downloads/Archive/augmented",
        weights="yolo11n.pt"
    )
