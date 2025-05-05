import torch
import torch.nn as nn
from ultralytics.nn.modules.conv import Conv
from ultralytics.nn.modules.block import C2f
from yolo_custom_head import HailoDetectHead

class HailoYOLOv11Nano(nn.Module):
    def __init__(self, nc=1):
        super().__init__()
        self.nc = nc

        # Backbone + neck
        self.stem = Conv(3, 32, 3, 2)
        self.conv1 = Conv(32, 64, 3, 2)
        self.c2f1 = C2f(64, 64, n=1)
        self.conv2 = Conv(64, 128, 3, 2)
        self.c2f2 = C2f(128, 128, n=2)
        self.conv3 = Conv(128, 256, 3, 2)
        self.c2f3 = C2f(256, 256, n=3)

        # Hailo detection head (outputs 6 channels: x, y, w, h, obj, class)
        self.head = HailoDetectHead(in_channels=256)

    def forward(self, x):
        x = self.stem(x)
        x = self.conv1(x)
        x = self.c2f1(x)
        x = self.conv2(x)
        x = self.c2f2(x)
        x = self.conv3(x)
        x = self.c2f3(x)
        return self.head(x)
