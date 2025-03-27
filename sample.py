import cv2
import numpy as np
import math

class DiskTracker:
    """
    This class processes frames to detect disks (via HoughCircles)
    and then detects off-center colored markers (blue and green) using HSV thresholding.
    It computes the rotation angle from the disk center to the marker.
    """
    def __init__(self):
        # HoughCircles parameters for disk detection (adjust these as needed)
        self.dp = 1.2
        self.minDist = 50
        self.param1 = 50
        self.param2 = 30
        self.minRadius = 20
        self.maxRadius = 100

        # HSV ranges for blue and green markers.
        # Adjust these values to match your lighting and marker colors.
        self.lower_blue = np.array([100, 150, 50])
        self.upper_blue = np.array([140, 255, 255])
        self.lower_green = np.array([40, 70, 70])
        self.upper_green = np.array([80, 255, 255])
    
    def process_frame(self, frame):
        output = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_blurred = cv2.medianBlur(gray, 5)

        # Detect circles (assumed to be disks)
        circles = cv2.HoughCircles(gray_blurred, cv2.HOUGH_GRADIENT, self.dp, self.minDist,
                                   param1=self.param1, param2=self.param2,
                                   minRadius=self.minRadius, maxRadius=self.maxRadius)

        if circles is not None:
            circles = np.uint16(np.around(circles))
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            for i in circles[0, :]:
                center = (i[0], i[1])
                radius = i[2]
                # Draw detected disk
                cv2.circle(output, center, radius, (0, 255, 0), 2)
                cv2.circle(output, center, 2, (0, 0, 255), 3)

                # Define a ROI around the disk, making sure the indices are within bounds
                x, y, r = i[0], i[1], radius
                x1, y1 = int(max(x - r, 0)), int(max(y - r, 0))
                x2, y2 = int(min(x + r, frame.shape[1] - 1)), int(min(y + r, frame.shape[0] - 1))
                
                # Check if ROI dimensions are valid
                if y2 - y1 <= 0 or x2 - x1 <= 0:
                    continue  # Skip if ROI is empty

                roi = hsv[y1:y2, x1:x2]

                # Detect blue and green markers in ROI
                mask_blue = cv2.inRange(roi, self.lower_blue, self.upper_blue)
                mask_green = cv2.inRange(roi, self.lower_green, self.upper_green)

                # Find contours for blue and green markers
                contours_blue, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                contours_green, _ = cv2.findContours(mask_green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                marker_center = None
                marker_color = None

                # Check blue contours first
                if contours_blue:
                    cnt = max(contours_blue, key=cv2.contourArea)
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"]) + x1
                        cY = int(M["m01"] / M["m00"]) + y1
                        marker_center = (cX, cY)
                        marker_color = (255, 0, 0)  # Blue marker (BGR)
                # If no blue, check for green
                elif contours_green:
                    cnt = max(contours_green, key=cv2.contourArea)
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"]) + x1
                        cY = int(M["m01"] / M["m00"]) + y1
                        marker_center = (cX, cY)
                        marker_color = (0, 255, 0)  # Green marker (BGR)

                if marker_center is not None:
                    # Draw the marker and a line from the disk center
                    cv2.circle(output, marker_center, 4, marker_color, -1)
                    cv2.line(output, center, marker_center, (255, 255, 0), 2)
                    # Compute the rotation angle (in degrees)
                    angle = math.degrees(math.atan2(marker_center[1] - center[1], marker_center[0] - center[0]))
                    cv2.putText(output, f"{angle:.1f} deg", (center[0]-40, center[1]-radius-10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return output

def main():
    # Change the path to your video file
    video_path = input("Enter the path to your video file: ").strip()
    cap = cv2.VideoCapture(video_path)
    tracker = DiskTracker()

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            print("End of video or cannot read the frame.")
            break

        # Optional: Pre-process the frame to "whiten" static background areas.
        # For example, you might subtract a pre-computed background model.
        # This could help if there are unwanted marks on the table.
        # Here, we leave it as is.

        processed_frame = tracker.process_frame(frame)
        cv2.imshow("Processed Frame", processed_frame)
        key = cv2.waitKey(30)  # Adjust delay as necessary for your video fps

        if key & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

