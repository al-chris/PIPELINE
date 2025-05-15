import requests
import cv2
import time

# Open the camera
cap = cv2.VideoCapture(0)

# Check if camera opened successfully
if not cap.isOpened():
    print("Error: Could not open camera.")
    exit()


port = 8000
url = "http://localhost"
rate = 0.25 # fps

is_configured = False

try:
    print("Starting continuous frame capture. Press Ctrl+C to stop.")
    
    while True:
        # Capture frame from camera
        ret, frame = cap.read()
        
        if not ret:
            print("Error: Failed to capture frame")
            continue
        
        # Encode the frame as JPEG
        _, img_encoded = cv2.imencode('.jpg', frame)
        
        # Send to the server
        files = {'file': ('image.jpg', img_encoded.tobytes(), 'image/jpeg')}
        
        try:
            # Using port 80 instead of 8000
            response = requests.post(
                f'{url}:{port}/annotate', 
                files=files,
                timeout=600  # Add timeout to prevent blocking
            )
            print(f"Frame sent. Response: {response.json()}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending frame: {e}")

        
        
        # Control frame rate
        time.sleep(1/rate) 

except KeyboardInterrupt:
    print("\nStopping frame capture")
finally:
    # Release the camera
    cap.release()