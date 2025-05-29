import gi
gi.require_version('Gst', '1.0')  # Add explicit version requirement
import os
import cv2
import hailo
import time
import json
import threading
import serial
import numpy as np
import datetime
import gc
from collections import deque
from gi.repository import Gst, GLib
import boto3
import traceback
from threading import Lock, Event

from hailo_apps_infra.hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
    app_callback_class,
)
from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

# --------------------------------------------
# Configuration
# --------------------------------------------
Gst.init(None)

# Force GStreamer to not buffer too many frames
os.environ['GST_BUFFER_MAX_SIZE'] = '2000000'  # Limit buffer size to 2MB

# Tigris (S3-compatible) bucket config
S3_URL = os.getenv("S3_URL", "https://fly.storage.tigris.dev/")
TIGRIS_BUCKET_NAME = os.getenv("TIGRIS_BUCKET_NAME", "pothole-images")

# CRITICAL: Reduce capture resolution to lower memory pressure
CAPTURE_WIDTH = 640   # Reduced from 1280
CAPTURE_HEIGHT = 480  # Reduced from 720

# Initialize S3 client
try:
    s3_client = boto3.client(
        's3',
        endpoint_url=S3_URL,
        aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
    )
except Exception as e:
    print(f"[WARN] S3 client initialization failed: {e}")
    s3_client = None

# --------------------------------------------
# Global Variables with Thread Safety
# --------------------------------------------
# Thread locks
serial_lock = Lock()
frame_buffer_lock = Lock()

# Shutdown event for clean termination
shutdown_event = Event()

# GPS data
latest_serial_data = {"raw": "", "lat": None, "lon": None}

# Frame buffer settings - reduced from 300 to 90 frames (~3 seconds at 30fps)
# This is a critical change to reduce memory pressure
FRAME_BUFFER = deque(maxlen=90)
RECORDING = False
LAST_DETECTION_TIME = 0
DETECTION_TIMEOUT = 3

# Base output directory
OUTPUT_BASE_DIR = "cached_clips"
os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

# Add memory management monitor
def memory_monitor():
    import psutil
    process = psutil.Process(os.getpid())
    while not shutdown_event.is_set():
        try:
            rss = process.memory_info().rss / (1024 * 1024)
            print(f"[MEM] RSS: {rss:.1f} MB")
            # Force garbage collection if memory exceeds threshold
            if rss > 200:  # Lower threshold from 250 to 200
                print("[MEM] High memory detected, forcing garbage collection")
                gc.collect()
            time.sleep(5)
        except Exception as e:
            print(f"[WARN] Memory monitor error: {e}")
            time.sleep(1)

# --------------------------------------------
# Serial Reader for GPS metadata
# --------------------------------------------
def read_serial():
    """ Continuously read NMEA lines and parse latitude/longitude. """
    global latest_serial_data
    try:
        ser = serial.Serial("/dev/serial0", 9600, timeout=1)
        while not shutdown_event.is_set():
            try:
                line = ser.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    time.sleep(0.1)
                    continue
                    
                if line.startswith("$GPGGA") or line.startswith("$GPRMC"):
                    # Use a more atomic update approach to reduce lock time
                    parsed_data = {"raw": line}
                    parts = line.split(',')
                    
                    if line.startswith("$GPRMC") and len(parts) > 6 and parts[2] == 'A':
                        try:
                            lat = float(parts[3][:2]) + float(parts[3][2:]) / 60.0
                            if parts[4] == 'S': lat = -lat
                            lon = float(parts[5][:3]) + float(parts[5][3:]) / 60.0
                            if parts[6] == 'W': lon = -lon
                            parsed_data.update({"lat": lat, "lon": lon})
                        except (ValueError, IndexError) as e:
                            print(f"[WARN] Failed to parse GPRMC: {e}")
                            
                    elif line.startswith("$GPGGA") and len(parts) > 6 and parts[6] != '0':
                        try:
                            lat = float(parts[2][:2]) + float(parts[2][2:]) / 60.0
                            if parts[3] == 'S': lat = -lat
                            lon = float(parts[4][:3]) + float(parts[4][3:]) / 60.0
                            if parts[5] == 'W': lon = -lon
                            parsed_data.update({"lat": lat, "lon": lon})
                        except (ValueError, IndexError) as e:
                            print(f"[WARN] Failed to parse GPGGA: {e}")
                    
                    # Now do the actual update with the lock
                    with serial_lock:
                        latest_serial_data.update(parsed_data)
            except Exception as e:
                print(f"[WARN] Serial read error: {e}")
                time.sleep(1)  # Avoid CPU spinning on errors
    except Exception as e:
        print(f"[ERROR] Serial Thread: {e}")
        print(traceback.format_exc())
    finally:
        print("[INFO] Serial thread exiting")
        try:
            ser.close()
        except:
            pass

# --------------------------------------------
# Safe frame copy function
# --------------------------------------------
def safe_frame_copy(frame):
    """Create a safe copy of a frame or return None if the frame is invalid"""
    if frame is None:
        return None
    
    try:
        # Check if frame has valid dimensions and content
        if frame.size == 0 or frame.shape[0] == 0 or frame.shape[1] == 0:
            return None
            
        # Create a copy - use .copy() which is safer than np.copy()
        return frame.copy()
    except Exception as e:
        print(f"[WARN] Frame copy error: {e}")
        return None

# --------------------------------------------
# Save clip, best frame, and metadata (with upload)
# --------------------------------------------
def save_clip_and_metadata(frames_data):
    try:
        print(f"[DEBUG] save_clip_and_metadata() triggered with {len(frames_data)} frames")
        if not frames_data:
            print("[WARN] No frames to save, aborting")
            return

        # Create daily directory
        date_str = datetime.date.today().isoformat()
        output_dir = os.path.join(OUTPUT_BASE_DIR, date_str)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = int(time.time())
        video_name = f"pothole_{timestamp}.avi"
        json_name = f"pothole_{timestamp}.json"
        bestframe_name = f"pothole_{timestamp}_best.jpg"
        video_path = os.path.join(output_dir, video_name)
        metadata_path = os.path.join(output_dir, json_name)
        bestframe_path = os.path.join(output_dir, bestframe_name)

        # Get GPS data safely
        with serial_lock:
            lat = latest_serial_data.get('lat')
            lon = latest_serial_data.get('lon')

        # Filter out invalid frames
        valid_frames = []
        for entry in frames_data:
            if entry['frame'] is not None and entry['frame'].size > 0:
                valid_frames.append(entry)
        
        if not valid_frames:
            print("[ERROR] No valid frames to process")
            return
            
        # Ensure all frames have the same dimensions - use first frame as reference
        first_valid = valid_frames[0]['frame']
        h, w = first_valid.shape[0], first_valid.shape[1]
        
        # Write video
        out = None
        try:
            out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'XVID'), 30, (w, h))
            if not out.isOpened():
                print(f"[ERROR] VideoWriter failed to open for {video_path}")
                return
                
            for entry in valid_frames:
                frame = entry['frame']
                # Ensure frame has correct dimensions
                if frame.shape[0] != h or frame.shape[1] != w:
                    try:
                        frame = cv2.resize(frame, (w, h))
                    except Exception as e:
                        print(f"[WARN] Frame resize error: {e}")
                        continue
                out.write(frame)
                
        except Exception as e:
            print(f"[ERROR] Video writing failed: {e}")
        finally:
            if out is not None:
                try:
                    out.release()
                except Exception:
                    pass
            
        print(f"[INFO] Saved video: {video_path}")

        # Select best frame: center y closest to 50%
        try:
            best_idx, best_diff = None, float('inf')
            for i, entry in enumerate(valid_frames):
                for yc in entry.get('y_centers', []):
                    diff = abs(yc - 0.5)
                    if diff < best_diff:
                        best_diff = diff
                        best_idx = i
                        
            if best_idx is not None:
                cv2.imwrite(bestframe_path, valid_frames[best_idx]['frame'])
                print(f"[INFO] Saved best frame: {bestframe_path}")
            else:
                # Save first frame as fallback
                cv2.imwrite(bestframe_path, valid_frames[0]['frame'])
                print(f"[INFO] No detection centers, saved first frame as best: {bestframe_path}")
        except Exception as e:
            print(f"[ERROR] Best frame saving failed: {e}")

        # Write metadata
        try:
            meta = {
                "timestamp": timestamp,
                "gps": {"lat": lat, "lon": lon},
            }
            with open(metadata_path, 'w') as fjson:
                json.dump(meta, fjson)
            print(f"[INFO] Saved metadata: {metadata_path}")
        except Exception as e:
            print(f"[ERROR] Metadata saving failed: {e}")

        # Upload to S3 if client is available
        if s3_client:
            for fname, key in [(video_name, video_name), (json_name, json_name), (bestframe_name, bestframe_name)]:
                local = os.path.join(output_dir, fname)
                if not os.path.exists(local):
                    print(f"[WARN] File {local} not found for upload")
                    continue
                    
                s3_key = f"{date_str}/{fname}"
                try:
                    s3_client.upload_file(local, TIGRIS_BUCKET_NAME, s3_key)
                    print(f"[INFO] Uploaded {fname} to S3://{TIGRIS_BUCKET_NAME}/{s3_key}")
                except Exception as e:
                    print(f"[ERROR] Failed to upload {fname}: {e}")
                    
        # Force garbage collection after saving to free memory
        gc.collect()
    except Exception as e:
        print(f"[ERROR] save_clip_and_metadata failed: {e}")
        print(traceback.format_exc())

# --------------------------------------------
# Callback class
# --------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True
        self.last_frame_time = time.time()
        self.frame_count = 0
        
    def check_frame_rate(self):
        """Monitor frame processing rate for debugging"""
        self.frame_count += 1
        now = time.time()
        if now - self.last_frame_time > 5:  # Check every 5 seconds
            fps = self.frame_count / (now - self.last_frame_time)
            print(f"[INFO] Processing at {fps:.1f} FPS")
            self.frame_count = 0
            self.last_frame_time = now

# --------------------------------------------
# Main Detection Callback
# --------------------------------------------
def app_callback(pad, info, user_data):
    global RECORDING, LAST_DETECTION_TIME, FRAME_BUFFER
    
    try:
        user_data.check_frame_rate()
        
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK

        user_data.use_frame = True
        fmt, w, h = get_caps_from_pad(pad)
        frame = None
        
        # Early validation
        if not fmt or not w or not h or w <= 0 or h <= 0:
            return Gst.PadProbeReturn.OK

        # Handle frame conversion carefully
        try:
            frame = get_numpy_from_buffer(buf, fmt, w, h)
            if frame is not None and frame.size > 0:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            else:
                return Gst.PadProbeReturn.OK
        except Exception as e:
            print(f"[WARN] Frame conversion error: {e}")
            return Gst.PadProbeReturn.OK

        # Process detections - with error handling
        dets = []
        try:
            roi = hailo.get_roi_from_buffer(buf)
            if roi is not None:
                dets = roi.get_objects_typed(hailo.HAILO_DETECTION)
        except Exception as e:
            print(f"[WARN] Detection processing error: {e}")
            
        y_centers = []
        pothole = False
        
        if frame is not None and frame.size > 0:
            # Process detections
            for det in dets:
                try:
                    if det.get_class_id() == 1:
                        pothole = True
                    bbox = det.get_bbox()
                    yc = (bbox.ymin() + bbox.ymax()) / 2.0
                    y_centers.append(yc)
                    
                    # Draw bounding box
                    x0, y0 = int(bbox.xmin() * w), int(bbox.ymin() * h)
                    x1, y1 = int(bbox.xmax() * w), int(bbox.ymax() * h)
                    cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 255, 0), 2)
                except Exception as e:
                    print(f"[WARN] Bounding box error: {e}")
                    
            # Add GPS overlay
            with serial_lock:
                lat, lon = latest_serial_data.get("lat"), latest_serial_data.get("lon")
                
            gps_text = f"Lat:{lat:.6f} Lon:{lon:.6f}" if lat and lon else "GPS unavailable"
            cv2.putText(frame, gps_text, (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # Update recording state
        current_time = time.time()
        
        # Make a safe copy of the frame before adding to buffer
        safe_frame = safe_frame_copy(frame) if frame is not None else None
        
        with frame_buffer_lock:
            if pothole and safe_frame is not None:
                LAST_DETECTION_TIME = current_time
                if not RECORDING:
                    RECORDING = True
                    print("[INFO] Recording started")
                FRAME_BUFFER.append({'frame': safe_frame, 'y_centers': y_centers})
            elif RECORDING and safe_frame is not None:
                # Keep buffering until timeout
                FRAME_BUFFER.append({'frame': safe_frame, 'y_centers': y_centers})
            
            # Check for end of event with timeout
            if RECORDING and (current_time - LAST_DETECTION_TIME > DETECTION_TIMEOUT):
                RECORDING = False
                # Make a copy to avoid thread issues
                clip = list(FRAME_BUFFER)
                FRAME_BUFFER.clear()
                # Process in separate thread to avoid blocking GStreamer pipeline
                threading.Thread(target=save_clip_and_metadata, args=(clip,), daemon=True).start()
                print(f"[INFO] Detection ended, saving clip with {len(clip)} frames")
    
    except Exception as e:
        print(f"[ERROR] app_callback failed: {e}")
        print(traceback.format_exc())
    
    return Gst.PadProbeReturn.OK

# --------------------------------------------
# Custom GStreamerDetectionApp Subclass to Fix PiCamera Issues
# --------------------------------------------
class SafeGStreamerDetectionApp(GStreamerDetectionApp):
    def __init__(self, callback, user_callback_class):
        super().__init__(callback, user_callback_class)
        self.picamera = None
        
    def cleanup(self):
        """Properly clean up resources"""
        self.picamera_running = False
        shutdown_event.set()
        # Wait for threads to exit gracefully
        time.sleep(1)
        if hasattr(self, 'picam2') and self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
        
    def picamera_thread(self):
        """Override the picamera thread method to handle errors better"""
        try:
            print("[INFO] PiCamera thread starting")
            # Critical change: Use lower resolution to reduce memory usage
            from picamera2 import Picamera2
            
            # Create a new camera instance
            self.picam2 = Picamera2()
            
            # Configure with more conservative settings
            config = self.picam2.create_video_configuration(
                main={"size": (CAPTURE_WIDTH, CAPTURE_HEIGHT), "format": "RGB888"},
                buffer_count=2,  # Reduce buffer count to minimize memory usage
                queue=False      # Disable internal queue to reduce memory usage
            )
            
            print(f"[INFO] Picamera2 configuration: width={config['main']['size'][0]}, height={config['main']['size'][1]}, format={config['main']['format']}")
            
            # Apply configuration
            self.picam2.configure(config)
            
            # Add small delay before starting
            time.sleep(0.5)
            
            # Start camera
            self.picam2.start()
            print("[INFO] Picamera process started")
            
            # Add small delay after starting
            time.sleep(0.5)
            
            # Frame drop counter to monitor performance
            dropped_frames = 0
            last_report_time = time.time()
            
            while self.picamera_running and not shutdown_event.is_set():
                try:
                    # Use capture_array with timeout protection
                    start_time = time.time()
                    array = self.picam2.capture_array()
                    capture_time = time.time() - start_time
                    
                    # Debug capture time if it's too slow
                    if capture_time > 0.1:
                        print(f"[WARN] Slow frame capture: {capture_time:.3f}s")
                    
                    if array is None or array.size == 0:
                        print("[WARN] Empty frame captured, skipping")
                        dropped_frames += 1
                        time.sleep(0.03)
                        continue
                    
                    # Validate array dimensions    
                    if len(array.shape) != 3 or array.shape[2] != 3:
                        print(f"[WARN] Invalid frame shape: {array.shape}, skipping")
                        dropped_frames += 1
                        time.sleep(0.03)
                        continue
                        
                    # Push to HailoRT - wrapped in try block
                    try:
                        self.hailo_push_buffer(array)
                    except Exception as e:
                        print(f"[WARN] Failed to push buffer: {e}")
                        dropped_frames += 1
                        time.sleep(0.03)
                        continue
                        
                    # Report dropped frames periodically
                    now = time.time()
                    if now - last_report_time > 10:
                        if dropped_frames > 0:
                            print(f"[INFO] Dropped {dropped_frames} frames in last 10 seconds")
                        dropped_frames = 0
                        last_report_time = now
                        
                    # Short sleep to prevent CPU overload - critical for stability
                    time.sleep(0.01)
                    
                except Exception as e:
                    print(f"[ERROR] Frame capture error: {e}")
                    traceback.print_exc()
                    dropped_frames += 1
                    time.sleep(0.1)  # Sleep longer on errors
                    
        except Exception as e:
            print(f"[FATAL] PiCamera thread crashed: {e}")
            traceback.print_exc()
        finally:
            print("[INFO] PiCamera thread exiting")
            # Clean up camera resources
            try:
                if hasattr(self, 'picam2') and self.picam2:
                    self.picam2.stop()
                    self.picam2.close()
                    self.picam2 = None
            except Exception as e:
                print(f"[ERROR] Failed to close camera: {e}")

# --------------------------------------------
# Signal handling for graceful shutdown
# --------------------------------------------
import signal

def signal_handler(sig, frame):
    print("[INFO] Caught signal, shutting down...")
    shutdown_event.set()
    # Give threads time to clean up
    time.sleep(1)
    # Force exit if cleanup is taking too long
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --------------------------------------------
# Main entry
# --------------------------------------------
if __name__ == "__main__":
    app = None
    try:
        print("[INFO] Starting pothole detection system...")
        
        # Start memory monitor
        threading.Thread(target=memory_monitor, daemon=True).start()
        
        # Start serial thread
        serial_thread = threading.Thread(target=read_serial, daemon=True)
        serial_thread.start()
        print("[INFO] Serial thread started")
        
        # Use our safer app class instead of the original
        app = SafeGStreamerDetectionApp(app_callback, user_app_callback_class())
        print("[INFO] Running GStreamer pipeline")
        app.run()
    except Exception as e:
        print(f"[FATAL] Main application error: {e}")
        print(traceback.format_exc())
    finally:
        # Ensure proper cleanup
        shutdown_event.set()
        if app:
            try:
                app.cleanup()
            except:
                pass
        print("[INFO] Application shutdown complete")