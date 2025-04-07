import os
import shutil
import torch
import numpy as np
import pandas as pd
from tqdm import tqdm
from base64 import b64encode
from ultralytics import YOLO
from IPython.display import Image, HTML
import supervision as sv
import cv2
from collections import defaultdict

# Paths
DATA_YML_PATH = r'E:\Downloads\Archive\data.yaml'
RESULTS_PATH = r'E:\Downloads\Archive\results'
WEIGHTS = 'yolo11n.pt'  # Ensure the correct YOLOv11 model weights are used
BATCH_SIZE = 64


def train_yolo_with_multi_gpu(
    data_path: str = DATA_YML_PATH,
    epochs: int = 150,
    batch_size: int = BATCH_SIZE,
    weights: str = WEIGHTS,
    imgsz: int = 640,
    devices: str = '0', 
    **kwargs
) -> None:
    """
    Train YOLOv11 using multiple GPUs if available.
    """
    print("Initializing YOLOv11 Model...")
    model = YOLO(weights)  # Load YOLOv11 model
    
    model.train(
        data=data_path,
        epochs=epochs,
        batch=batch_size,
        imgsz=imgsz,
        device=devices,  # Assign GPUs
        **kwargs
    )


def process_frame(frame: np.ndarray, _) -> np.ndarray:
    """
    Process a frame for inference using YOLOv11.
    """
    results = model(frame, imgsz=1280)[0]
    detections = sv.Detections.from_yolo_nas(results)
    box_annotator = sv.BoxAnnotator(thickness=4, text_thickness=4, text_scale=2)
    labels = [f"{model.names[class_id]} {confidence:0.2f}" for _, _, confidence, class_id, _ in detections]
    frame = box_annotator.annotate(scene=frame, detections=detections, labels=labels)
    return frame


if __name__ == "__main__":
    print("Is CUDA available:", torch.cuda.is_available())
    print("Number of GPUs:", torch.cuda.device_count())
    if torch.cuda.is_available():
        print("CUDA Device Name:", torch.cuda.get_device_name(0))
    else:
        print("No GPU detected, training on CPU (may be slow)")
    
    # Train the model
    # train_yolo_with_multi_gpu()
    
    # Video inference setup
    VIDEO_PATH = r"E:\\Downloads\\Archive\\sample_video.mp4"
    model = YOLO("./runs/detect/train17/weights/best.pt")  # Load the best trained weights
    
    # Uncomment the following line to run video inference
    model.predict(source=VIDEO_PATH, save=True, imgsz=320, conf=0.5)
