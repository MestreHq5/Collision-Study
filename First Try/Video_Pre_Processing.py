import cv2
import numpy as np

# Initialize video capture
cap = cv2.VideoCapture(r'C:\Users\gonca\Desktop\Collisions DEM\Collision-Study\Video1.mp4')

# Enhanced processing parameters
params = {
    'gaussian_blur': (5, 5),        # Increased for better noise reduction
    'threshold': 40,                # Adjusted for better sensitivity
    'canny_thresholds': (75, 150),  # Higher thresholds for cleaner edges
    'morph_kernel': np.ones((7,7), np.uint8),  # Larger kernel for better closure
    'min_contour_area': 800,        # Increased to filter small artifacts
    'min_circularity': 0.7,        # Adjusted for collision tolerance
    'background_learning_rate': 0.0005,  # Slower adaptation
    'tracking_history': 20,         # Longer memory for disappeared objects
    'motion_persistence': 5,         # Frames to keep vanished objects
    'border_percent': 0.15
}

# Initialize video writer
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS)
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter('output_video.mp4', fourcc, fps, (frame_width, frame_height))

# Initialize background with average of first 30 frames
print("Initializing background model...")
background_frames = []
for _ in range(30):
    ret, frame = cap.read()
    if ret:
        background_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset video position

background_gray = np.median(background_frames, axis=0).astype(np.uint8)

# Tracking system
class TrackedObject:
    def __init__(self, contour, position):
        self.contours = [contour]
        self.positions = [position]
        self.last_seen = 0
    
    def update(self, contour, position):
        self.contours.append(contour)
        self.positions.append(position)
        self.last_seen = 0
        
    def predict(self):
        # Simple linear prediction based on last 2 positions
        if len(self.positions) > 1:
            dx = self.positions[-1][0] - self.positions[-2][0]
            dy = self.positions[-1][1] - self.positions[-2][1]
            return (self.positions[-1][0] + dx, self.positions[-1][1] + dy)
        return self.positions[-1]

tracked_objects = []

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Preprocessing
    current_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.GaussianBlur(current_gray, params['gaussian_blur'], 0)
    
    # Update background model (very slow adaptation)
    background_gray = cv2.addWeighted(
        background_gray, 0.9995,
        current_gray, 0.0005,
        0
    )
    
    # Motion detection with dynamic threshold
    diff = cv2.absdiff(background_gray, current_gray)
    diff_mean = np.mean(diff)
    adaptive_thresh = max(params['threshold'], diff_mean * 1.5)
    _, thresh = cv2.threshold(diff, adaptive_thresh, 255, cv2.THRESH_BINARY)
    
    # Clean detection
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, params['morph_kernel'], iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, params['morph_kernel'], iterations=1)
    
    # Contour processing
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    current_objects = []
    object_mask = np.zeros_like(cleaned)
    
    # Process detected contours
    for cnt in contours:
        perimeter = cv2.arcLength(cnt, True)
        area = cv2.contourArea(cnt)
        
        if perimeter == 0 or area < params['min_contour_area']:
            continue
            
        circularity = 4 * np.pi * area / (perimeter**2)
        if circularity > params['min_circularity']:
            M = cv2.moments(cnt)
            if M['m00'] != 0:
                cx = int(M['m10']/M['m00'])
                cy = int(M['m01']/M['m00'])
                current_objects.append((cx, cy, cnt))
    
    # Tracking and prediction
    active_ids = []
    for obj in tracked_objects:
        obj.last_seen += 1
    
    # Match current detections with tracked objects
    for cx, cy, cnt in current_objects:
        matched = False
        for obj in tracked_objects:
            last_pos = obj.positions[-1]
            distance = np.sqrt((cx - last_pos[0])**2 + (cy - last_pos[1])**2)
            
            if distance < 50 and obj.last_seen < params['motion_persistence']:
                obj.update(cnt, (cx, cy))
                active_ids.append(id(obj))
                matched = True
                break
        
        if not matched:
            tracked_objects.append(TrackedObject(cnt, (cx, cy)))
            active_ids.append(id(tracked_objects[-1]))
    
    # Remove stale objects and create mask
    final_mask = np.zeros_like(cleaned)
    for obj in tracked_objects[:]:
        if id(obj) not in active_ids and obj.last_seen > params['motion_persistence']:
            tracked_objects.remove(obj)
        else:
            # Use prediction for missing frames
            if obj.last_seen > 0:
                pred_pos = obj.predict()
                cv2.circle(final_mask, (int(pred_pos[0]), int(pred_pos[1])), 
                          int(np.sqrt(obj.contours[-1].shape[0]/np.pi)), 255, -1)
            else:
                cv2.drawContours(final_mask, [obj.contours[-1]], -1, 255, -1)
    
    # Add current detections
    for cx, cy, cnt in current_objects:
        cv2.drawContours(final_mask, [cnt], -1, 255, -1)
    
    # Post-process mask
    final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, params['morph_kernel'], iterations=1)
    
    # Final composition
    white_bg = np.full_like(frame, 255)
    result = cv2.bitwise_and(white_bg, white_bg, mask=cv2.bitwise_not(final_mask))
    result += cv2.bitwise_and(frame, frame, mask=final_mask)
    
    '''
    # Draw tracked paths
    for obj in tracked_objects:
        if len(obj.positions) > 1:
            pts = np.array(obj.positions, np.int32).reshape((-1,1,2))
            cv2.polylines(result, [pts], False, (0,255,0), 2)
    '''
    
    # Write output
    out.write(result)
    
    cv2.imshow('Tracking', result)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
out.release()
cv2.destroyAllWindows()