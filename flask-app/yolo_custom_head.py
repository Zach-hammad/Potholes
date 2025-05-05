import torch
import torch.nn as nn

class HailoDetectHead(nn.Module):
    def __init__(self, in_channels):
        super().__init__()
        self.head = nn.Conv2d(in_channels, 6, kernel_size=1)

    def forward(self, x):
        if isinstance(x, (list, tuple)):
            x = x[0]  # Use highest-resolution map if list
        return self.head(x)
