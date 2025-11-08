# QR Code Scanner

A simple Python application that uses OpenCV to scan multiple QR codes from a live camera feed and display their quadrilateral coordinates and contained information.

## Features

- Real-time QR code detection from camera feed
- Supports multiple QR codes in a single frame
- Displays bounding boxes around detected QR codes
- Shows decoded information and quadrilateral coordinates
- Resizable windows that don't take over the full screen
- Console output with detailed information
- Support for both live camera and static image processing

## Installation

1. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Live Camera Mode
Run the QR code scanner with your camera:

```bash
python coordinator/vision.py
```

Use a specific camera (if you have multiple):

```bash
python coordinator/vision.py -c 1
```

### Static Image Mode
Process a static image containing QR codes:

```bash
python coordinator/vision.py path/to/your/image.jpg
```

### Command Line Options

- `image`: Path to image file to process (optional)
- `-c, --camera CAMERA`: Camera index to use (default: 0)
- `-h, --help`: Show help message

### Examples

```bash
# Scan with default camera
python coordinator/vision.py

# Scan with camera index 1
python coordinator/vision.py -c 1

# Process static image
python coordinator/vision.py my_qr_codes.jpg

# Show help
python coordinator/vision.py --help
```

## Window Behavior

Both camera and image modes now use resizable windows:

- **Camera Mode**: Window starts at 1280x720 resolution but can be resized
- **Image Mode**: Images are automatically scaled down to fit within 800x600 pixels while maintaining aspect ratio, and the window is resizable

You can resize any window by dragging the corners, and press 'q' (camera mode) or any key (image mode) to close.

## Output

For each detected QR code, the application provides:

- **Data**: The decoded information stored in the QR code
- **Quadrilateral**: The four corner coordinates of the QR code bounding box

Example console output:
```
Frame 30: Detected 2 QR code(s)
  QR1:
    Data: https://example.com
    Quadrilateral: [[100, 150], [200, 150], [200, 250], [100, 250]]
  QR2:
    Data: Hello World!
    Quadrilateral: [[300, 100], [400, 100], [400, 200], [300, 200]]
```

## Requirements

- Python 3.6+
- OpenCV 4.5.0+
- Camera device (webcam, etc.) for live scanning

## Notes

- The application uses OpenCV's built-in QRCodeDetector which supports multiple QR codes per frame
- Camera resolution is set to 1280x720 for optimal performance
- Information is printed to console every 30 frames to avoid spam
- Windows are resizable to accommodate different screen sizes
