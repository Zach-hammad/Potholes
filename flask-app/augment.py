import albumentations as A
import cv2
import os
import numpy as np
from glob import glob
from tqdm import tqdm


# Augmentation pipeline (fixed)
augment = A.Compose([
    A.HorizontalFlip(p=0.5),
    A.RandomBrightnessContrast(p=0.5),
    A.HueSaturationValue(hue_shift_limit=10, sat_shift_limit=15, val_shift_limit=10, p=0.3),
    A.Rotate(limit=15, p=0.4),
    A.GaussianBlur(blur_limit=3, p=0.2),
    A.ShiftScaleRotate(shift_limit=0.1, scale_limit=0.2, rotate_limit=0, p=0.5),  # replaces TranslateX/Y + RandomScale
], bbox_params=A.BboxParams(format='yolo', label_fields=['class_labels'], min_visibility=0.3))


def augment_yolo_dataset(images_dir, labels_dir, output_dir, num_augments=3):
    os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "labels"), exist_ok=True)

    image_paths = glob(os.path.join(images_dir, '*.jpg'))

    for img_path in tqdm(image_paths):
        try:
            img = cv2.imread(img_path)
            h, w = img.shape[:2]

            label_path = os.path.join(labels_dir, os.path.basename(img_path).replace('.jpg', '.txt').replace('_best', ''))
            if not os.path.exists(label_path):
                continue

            with open(label_path, 'r') as f:
                lines = f.readlines()

            bboxes = []
            class_labels = []
            for line in lines:
                cls, x, y, bw, bh = map(float, line.strip().split())
                bboxes.append([x, y, bw, bh])
                class_labels.append(int(cls))

            for i in range(num_augments):
                try:
                    augmented = augment(image=img, bboxes=bboxes, class_labels=class_labels)
                    aug_img = augmented['image']
                    aug_bboxes = augmented['bboxes']
                    aug_labels = augmented['class_labels']

                    out_img_path = os.path.join(output_dir, 'images', f"{os.path.splitext(os.path.basename(img_path))[0]}_aug{i}.jpg")
                    out_label_path = os.path.join(output_dir, 'labels', f"{os.path.splitext(os.path.basename(img_path))[0]}_aug{i}.txt")

                    cv2.imwrite(out_img_path, aug_img)

                    with open(out_label_path, 'w') as f:
                        for label, bbox in zip(aug_labels, aug_bboxes):
                            f.write(f"{label} {' '.join(map(str, bbox))}\n")

                except Exception as e:
                    print(f"Skipping augmentation due to error on {img_path}: {e}")
        except Exception as e:
            print(f"Skipping augmentation due to error on {img_path}: {e}")

if __name__ == "__main__":
    augment_yolo_dataset(
    images_dir=r"E:\Downloads\pothole_files\images",
    labels_dir=r"E:\Downloads\pothole_files\labels",
    output_dir=r"E:\Downloads\pothole_files\augmented\train",
    num_augments=4
)
