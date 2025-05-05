import numpy as np # linear algebra
import pandas as pd # data processing, CSV file I/O (e.g. pd.read_csv)




# Input data files are available in the read-only "../input/" directory
# For example, running this (by clicking run or pressing Shift+Enter) will list all files under the input directory

import os
# for dirname, _, filenames in os.walk("E:\Downloads\Archive"):
#     for filename in filenames:
#         print(os.path.join(dirname, filename))
#         break

import shutil
import os
import torch
from base64 import b64encode
from ultralytics import YOLO
from IPython.display import Image, HTML
from tqdm import tqdm



data_yml_path = r"E:\Downloads\Archive\data.yaml"
results_path = r"E:\Downloads\Archive\results"
weights = 'yolo11n.pt' # https://docs.ultralytics.com/models/
batch_size = 64
def train_yolo_with_multi_gpu(
    data_path: str = data_yml_path,
    # data_path: str = 'E:\Downloads\Archive\data.yaml',
    epochs: int = 350,
    batch_size: int = batch_size,
    weights: str = weights,
    imgsz: int = 640,
    devices: str = '0', 
    **kwargs
) -> None:
    
   
    model = YOLO(weights)
    
    
    model.train(
        data=data_path,
        epochs=epochs,
        batch=batch_size,
        imgsz=imgsz,
        device=devices,  
        **kwargs
    )
def process_frame(frame: np.ndarray, _) -> np.ndarray:
    results = model(frame, imgsz=1280)[0]
    
    detections = sv.Detections.from_yolo_nas(results)

    box_annotator = sv.BoxAnnotator(thickness=4, text_thickness=4, text_scale=2)

    labels = [f"{model.names[class_id]} {confidence:0.2f}" for _, _, confidence, class_id, _ in detections]
    frame = box_annotator.annotate(scene=frame, detections=detections, labels=labels)

    return frame

# Jalankan pelatihan
if __name__ == "__main__":
    print("Is CUDA available:", torch.cuda.is_available())
    print("Number of GPUs:", torch.cuda.device_count())
    print("CUDA Device Name:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU")
    train_yolo_with_multi_gpu()
    
    import ultralytics
    import supervision
    import torch
    import cv2
    from collections import defaultdict
    import supervision as sv
    from ultralytics import YOLO
    

    # VIDEO_PATH = r"E:\Downloads\Archive\sample_video.mp4"
    # model = YOLO("./runs/detect/train15/weights/best.pt")
    # model.predict(source=VIDEO_PATH, save=True, imgsz=320, conf=0.5)
    
    # video_info = sv.VideoInfo.from_video_path(VIDEO_PATH)
    # sv.process_video(source_path=VIDEO_PATH, target_path=f"result.mp4", callback=process_frame)

    