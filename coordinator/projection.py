import cv2
import numpy as np


class ProjectionMapper:
    """
    Handles the mapping of coordinates from a camera's view to the screen.
    """

    def __init__(self, screen_size, camera_size):
        """
        Initializes the mapper with screen and camera dimensions.
        Args:
            screen_size (tuple): (width, height) of the screen.
            camera_size (tuple): (width, height) of the camera frame.
        """
        self.screen_width, self.screen_height = screen_size
        self.camera_width, self.camera_height = camera_size
        self.homography_matrix = self._calculate_homography()

    def _calculate_homography(self):
        """
        Calculates the homography matrix for a direct mapping from camera
        view to screen.
        """
        # Source points are the corners of the camera frame
        src_points = np.float32(
            [
                [0, 0],
                [self.camera_width, 0],
                [self.camera_width, self.camera_height],
                [0, self.camera_height],
            ]
        )

        # Destination points are the corners of the screen
        dst_points = np.float32(
            [
                [0, 0],
                [self.screen_width, 0],
                [self.screen_width, self.screen_height],
                [0, self.screen_height],
            ]
        )

        # Compute the homography matrix
        matrix, _ = cv2.findHomography(src_points, dst_points)
        return matrix

    def map_points(self, points):
        """
        Maps a list of points from camera space to screen space.
        Args:
            points (np.ndarray): A numpy array of points (e.g., QR code corners)
                                 from the camera view. Shape should be (N, 1, 2).
        Returns:
            np.ndarray: The corresponding points in the screen's coordinate space.
        """
        if self.homography_matrix is None:
            return None

        # Ensure points are in the correct format (N, 1, 2) for perspectiveTransform
        if len(points.shape) != 3 or points.shape[1] != 1 or points.shape[2] != 2:
            # Reshape if it's a simple list of points like [[x,y], [x,y], ...]
            if len(points.shape) == 2 and points.shape[1] == 2:
                points = np.float32(points).reshape(-1, 1, 2)
            else:
                raise ValueError("Input points must be of shape (N, 1, 2) or (N, 2)")

        transformed_points = cv2.perspectiveTransform(
            np.float32(points), self.homography_matrix
        )
        transformed_points = cv2.perspectiveTransform(np.float32(points), self.homography_matrix)
        return transformed_points

    @staticmethod
    def get_bounding_box(points):
        """
        Calculates the axis-aligned bounding box for a set of points.
        Args:
            points (np.ndarray): An array of points.
        Returns:
            tuple: (x, y, w, h) for the bounding box, or None.
        """
        if points is None or len(points) == 0:
            return None

        # Squeeze out the unnecessary dimension if it exists
        if len(points.shape) == 3:
            points = np.squeeze(points, axis=1)

        x_coords = points[:, 0]
        y_coords = points[:, 1]

        x_min = int(np.min(x_coords))
        y_min = int(np.min(y_coords))
        x_max = int(np.max(x_coords))
        y_max = int(np.max(y_coords))

        width = x_max - x_min
        height = y_max - y_min

        if width <= 0 or height <= 0:
            return None

        return (x_min, y_min, width, height)
