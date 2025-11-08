#!/usr/bin/env python3
"""
QR Code Scanner using OpenCV
Scans multiple QR codes from live camera feed and displays their quadrilateral coordinates and contained information.
"""

import cv2
import sys
import numpy as np
import argparse


class QRCodeScanner:
    def __init__(self):
        """Initialize the QR code scanner with OpenCV detector."""
        self.qr_detector = cv2.QRCodeDetector()
        self.cap = None
        self.camera_index = 1

    def initialize_camera(self):
        """Initialize the camera capture."""
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            print(f"Error: Could not open camera {self.camera_index}")
            return False

        # Set camera properties for better performance
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        return True

    def detect_qr_codes(self, frame):
        """
        Detect QR codes in a frame and return their data and quadrilateral coordinates.

        Returns:
            list of tuples: [(data, points), ...] where points is a 4x2 numpy array of quadrilateral corners
        """
        qr_codes = []

        # Detect and decode QR codes
        retval, decoded_info, points, straight_qrcode = self.qr_detector.detectAndDecodeMulti(frame)

        if retval:
            # points is a list of 4x2 arrays, one for each detected QR code
            for i, (data, pts) in enumerate(zip(decoded_info, points)):
                if data:  # Only include QR codes with valid data
                    qr_codes.append((data, pts))

        return qr_codes

    def draw_qr_overlay(self, frame, qr_codes):
        """Draw bounding boxes and information overlay on the frame."""
        for i, (data, points) in enumerate(qr_codes):
            if points is not None:
                # Convert points to integer coordinates
                pts = points.astype(int)

                # Draw the quadrilateral outline
                cv2.polylines(frame, [pts], True, (0, 255, 0), 2)

                # Draw corner points
                for point in pts:
                    cv2.circle(frame, tuple(point), 5, (0, 0, 255), -1)

                # Calculate center point for text placement
                center_x = int(np.mean(pts[:, 0]))
                center_y = int(np.mean(pts[:, 1]))

                # Display QR code data
                text = f"QR{i+1}: {data[:20]}{'...' if len(data) > 20 else ''}"
                cv2.putText(frame, text, (center_x - 100, center_y - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2,
                           cv2.LINE_AA)

                # Display quadrilateral coordinates
                coords_text = f"Quad: {pts.tolist()}"
                cv2.putText(frame, coords_text, (center_x - 100, center_y + 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1,
                           cv2.LINE_AA)

        return frame

    def print_qr_info(self, qr_codes, frame_count):
        """Print QR code information to console."""
        if qr_codes:
            print(f"\nFrame {frame_count}: Detected {len(qr_codes)} QR code(s)")
            for i, (data, points) in enumerate(qr_codes):
                print(f"  QR{i+1}:")
                print(f"    Data: {data}")
                if points is not None:
                    print(f"    Quadrilateral: {points.astype(int).tolist()}")
        else:
            #print(f"Frame {frame_count}: No QR codes detected")
            pass

    def process_image(self, image_path):
        """Process a static image for QR codes."""
        frame = cv2.imread(image_path)
        if frame is None:
            print(f"Error: Could not load image from {image_path}")
            return

        print(f"Processing image: {image_path}")

        # Detect QR codes
        qr_codes = self.detect_qr_codes(frame)

        # Print information to console
        self.print_qr_info(qr_codes, 1)

        # Draw overlay on frame
        frame_with_overlay = self.draw_qr_overlay(frame.copy(), qr_codes)

        # Display the result in a resizable window
        window_name = 'QR Code Scanner - Image Mode'
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        # Resize window to fit screen while maintaining aspect ratio
        height, width = frame_with_overlay.shape[:2]
        max_width, max_height = 1280, 720

        # Calculate scaling factor to fit within max dimensions
        scale = min(max_width / width, max_height / height, 1.0)

        if scale < 1.0:
            new_width = int(width * scale)
            new_height = int(height * scale)
            frame_with_overlay = cv2.resize(frame_with_overlay, (new_width, new_height))

        cv2.imshow(window_name, frame_with_overlay)
        print("Press any key to close the image window...")

        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def run(self, image_path=None):
        """Main loop for QR code scanning."""
        if image_path:
            self.process_image(image_path)
            return

        if not self.initialize_camera():
            print("No camera available. You can also process static images:")
            print("Usage: python vision.py [image_path]")
            return

        print("QR Code Scanner started. Press 'q' to quit.")
        print("Detected QR codes will be displayed with bounding boxes and information.")

        # Create resizable window for camera feed
        window_name = 'QR Code Scanner'
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        frame_count = 0

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    print("Error: Could not read frame from camera")
                    break

                frame_count += 1

                # Detect QR codes
                qr_codes = self.detect_qr_codes(frame)

                # Print information to console
                if frame_count % 30 == 0:  # Print every 30 frames to avoid spam
                    self.print_qr_info(qr_codes, frame_count)

                # Draw overlay on frame
                frame_with_overlay = self.draw_qr_overlay(frame.copy(), qr_codes)

                # Display the frame
                cv2.imshow(window_name, frame_with_overlay)

                # Check for quit key
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        except KeyboardInterrupt:
            print("\nInterrupted by user")

        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up camera and OpenCV resources."""
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Camera and resources cleaned up.")


def main():
    """Main entry point."""
    # Check if OpenCV is available
    try:
        import cv2
        print(f"OpenCV version: {cv2.__version__}")
    except ImportError:
        print("Error: OpenCV is not installed. Please install with: pip install opencv-python")
        sys.exit(1)

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="QR Code Scanner using OpenCV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vision.py                    # Scan with live camera
  python vision.py image.jpg          # Process static image
  python vision.py -c 1               # Use camera index 1
        """
    )

    parser.add_argument('image', nargs='?', help='Path to image file to process (optional)')
    parser.add_argument('-c', '--camera', type=int, default=0,
                       help='Camera index to use (default: 0)')

    args = parser.parse_args()

    # Create and run the scanner
    scanner = QRCodeScanner()
    if args.image:
        scanner.run(args.image)
    else:
        # Set camera index if specified
        scanner.camera_index = args.camera
        scanner.run()


if __name__ == "__main__":
    main()
