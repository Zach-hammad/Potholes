import numpy as np # linear algebra
import pandas as pd # data processing, CSV file I/O (e.g. pd.read_csv)




# Input data files are available in the read-only "../input/" directory
# For example, running this (by clicking run or pressing Shift+Enter) will list all files under the input directory

import os
for dirname, _, filenames in os.walk('/kaggle/input'):
    for filename in filenames:
#         print(os.path.join(dirname, filename))
        break

import shutil
import os
import torch
from base64 import b64encode
from ultralytics import YOLO
from IPython.display import Image, HTML
from tqdm import tqdm


print("Is CUDA available:", torch.cuda.is_available())
print("Number of GPUs:", torch.cuda.device_count())
print("CUDA Device Name:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU")

data_yml_path = '/kaggle/input/potholes-detection-yolov8/data.yaml'
results_path = '/kaggle/working/runs/detect/'
weights = 'yolov8s.pt' # https://docs.ultralytics.com/models/
batch_size = 64
