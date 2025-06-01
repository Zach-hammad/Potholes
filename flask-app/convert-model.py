import torch

# Load your trained YOLOv5 model
model = torch.load('flask-app/best.pt', weights_only=False)['model'].float()
model.eval()

# Dummy input for tracing
dummy_input = torch.randn(1, 3, 640, 640)

# Export the model to ONNX format
torch.onnx.export(model, dummy_input, 'yolov5_model.onnx', opset_version=12)
