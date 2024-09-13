import cv2
import numpy as np
import time
import math
import subprocess
from PIL import Image
import imagehash
import notecard
from notecard import hub
from periphery import I2C
import base64
import threading
import json
import pluscodes
import queue
import binascii
import os
import sys
import traceback

# Constants
I2C_PORT = "/dev/i2c-1"
CHUNK_SIZE = 64  # Adjust chunk size based on your I2C bus stability
TIMEOUT_SECS = 5  # Increased timeout for large data transactions
CHUNK_RETRIES = 5  # Number of retries for each chunk
IMAGES_SENT_DB = "./IMAGES_SENT.json"  # File to store transmission state
PRODUCT_UID = "com.devmandan.daniel:cwd_cam"
CAM_INDEX = 1
PIR_PIN = 21

# Queue for communication between threads
task_queue = queue.Queue()

def calculate_crc(data):
    return binascii.crc32(data.encode('utf-8'))

def add_crc_to_request(req):
    """Add CRC to the request before sending it."""
    seqno = 1  # This should be incremented for each new request in practice
    data_to_crc = json.dumps(req)
    crc_value = format(calculate_crc(data_to_crc), '08X').upper()
    req['calc_crc'] = f"{seqno:04X}:{crc_value}"
    return req

def find_correct_CAM_INDEX(max_index=3):
    global CAM_INDEX
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret:
                CAM_INDEX = index
                print(f"Camera found at index: {index}")
                return index
    print("No valid camera index found.")
    return None

def capture_image():
    global CAM_INDEX
    cap = cv2.VideoCapture(CAM_INDEX)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return None

    ret, frame = cap.read()
    cap.release()

    if ret:
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return image
    else:
        print("Error: Failed to capture image.")
        return None


def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
        # url safe base64 encoding
        base64_encoded_data = base64.b64encode(image_data)
        base64_string = base64_encoded_data.decode('utf-8')
    print(base64_string)
    return base64_string

def setup_gpio(pin):
    try:
        result = subprocess.run(['gpio', 'mode', str(pin), 'input'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"GPIO {pin} is set to input mode.")
        else:
            print(f"Error setting GPIO {pin} to input mode: {result.stderr.strip()}")
    except Exception as e:
        print(f"An error occurred while setting up GPIO {pin}: {e}")

def pir_movement(pin):
    try:
        result = subprocess.run(['gpio', 'read', str(pin)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            value = result.stdout.strip()
            if value == '0':
                return False
            elif value == '1':
                print("Movement detected by PIR sensor!")
                return True
            else:
                print(f"Unexpected value read from GPIO {pin}: {value}")
                return None
        else:
            print(f"Error reading GPIO {pin}: {result.stderr.strip()}")
            return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def cam_movement(threshold, curr_image, curr_dhash, reference_dhash):
    if curr_dhash is None or reference_dhash is None:
        print("Error: Invalid image hash.")
        return False, None

    hamming_distance = reference_dhash - curr_dhash
    print(f"Hamming Distance: {hamming_distance}")

    if hamming_distance > threshold:
        print("Significant movement detected by camera!")
        return True, hamming_distance
    else:
        return False, hamming_distance

def compress_image(input_path, output_path, quality=100, scale_factor=1):
    with Image.open(input_path) as img:
        if scale_factor != 1:
            new_width = int(img.width // scale_factor)
            new_height = int(img.height // scale_factor)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=quality)

def crc_check(rsp):
    # CRC check
    if 'crc' in rsp:
        # Calculate CRC of the received data (excluding the CRC field itself)
        received_crc = rsp['crc'].split(':')[1]
        data_to_check = json.dumps({k: v for k, v in rsp.items() if k != 'crc'})
        calculated_crc = format(calculate_crc(data_to_check), '08X').upper()

        if received_crc != calculated_crc:
            print(f"CRC error: received {received_crc}, calculated {calculated_crc}")
        else:
            print("CRC check passed")
    else:
        print("No CRC found!")

def check_requests(nCard):
    req = {"req": "note.get", "file": "data.qi", "delete": True}
    # req = add_crc_to_request(req)  # Add CRC to the request
    try:
        rsp = nCard.Transaction(req)
        
        # Print the raw response for debugging
        print(f"Raw response: {rsp}")

        if rsp:
            crc_check(rsp)
                
            if 'body' in rsp:
                if rsp['body']:
                    print(f"Event received: {rsp['body']}")
                    if 'img_dhash' in rsp['body']:
                        print(rsp['body']['img_dhash'])
                        send_image_cell_data(nCard, rsp['body']['img_dhash'])
                else:
                    print("Key 'body' is empty in the response")
            elif 'err' in rsp:
                print("Error in response: ", rsp['err'])
            else:
                print("Unexpected response format: ", rsp)
        else:
            print("Empty response received")

        print("---")
        rsp_sync = hub.sync(nCard)
        print(f"Sync response: {rsp_sync}")
        print("---")
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def network_thread(nCard):
    while True:
        try:
            task = task_queue.get()
            if task['type'] == 'send_metadata':
                send_metadata_over_cell(nCard, task['c_dhash'], task['h_distance'], task['c_movement'], task['pir_movement'])
            elif task['type'] == 'check_for_requests':
                check_requests(nCard)
            else:
                print(f"Unknown task type: {task['type']}")
            
            task_queue.task_done()

        except Exception as e:
            print(f"An error occurred in the network thread: {e}")

def send_metadata_over_cell(nCard, c_dhash, h_distance, c_movement, pir_movement):
    gps_rsp = get_gps(nCard)
    plus_code = convert_to_plus_code(gps_rsp["lat"], gps_rsp["lon"])

    try:
        req = {
            "req": "note.add",
            "body": {
                "img_dhash": str(c_dhash),
                "h_dist": h_distance,
                "loc": plus_code
            }
        }
        # req = add_crc_to_request(req)  # Add CRC to the request

        rsp = nCard.Transaction(req)
        print("Raw Response:", rsp)
        crc_check(rsp)
        print("---")
    except Exception as e:
        print("Error during transaction:", str(e))

    try:
        print("Sending hub.sync request")
        rsp = hub.sync(nCard)
        print("Raw Sync Response:", rsp)

        print("---")
    except Exception as e:
        print("Error during transaction:", str(e))

def escape_base64(base64_string):
    """
    Escapes characters in a Base64 string that could interfere with JSON or other processing.
    
    Args:
        base64_string (str): The Base64 encoded string.
    
    Returns:
        str: The escaped Base64 string.
    """
    print(base64_string)
    # Replace characters that might interfere
    escaped_string = base64_string.replace('/', r'\/').replace('+', r'\+').replace('=', r'\=')
    return escaped_string

def handle_exception(e):
    """Handle exceptions by printing detailed error information."""
    exc_type, exc_obj, exc_tb = sys.exc_info()
    tb = traceback.extract_tb(exc_tb)
    
    print(f"Exception type: {exc_type.__name__}")
    print(f"Exception message: {e}")
    
    print("Traceback (most recent call last):")
    for i, frame in enumerate(tb):
        fname = os.path.split(frame.filename)[1]
        print(f"  File '{fname}', line {frame.lineno}, in {frame.name}")
        print(f"    {frame.line.strip()}")
    
    # Print the exact location where the exception occurred
    fname = os.path.split(tb[-1].filename)[1]
    print(f"Error occurred in: File '{fname}', Line {tb[-1].lineno}: {e}")
    print("Additional context:")
    print("  Operation failed during transaction with Notecard.")
    print("  Please check the connection and ensure the Notecard is operational.")


def sync_notecard(nCard):
    """Synchronize the Notecard with the cloud."""
    try:
        print("Synchronizing Notecard with the cloud...")
        rsp = hub.sync(nCard)
        print("Sync Response:", rsp)
    except Exception as e:
        handle_exception(e)

def chunk_data(data, chunk_size):
    """Yield successive chunks from data."""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]

def load_state():
    """Load the transmission state from a file."""
    if os.path.exists(IMAGES_SENT_DB):
        with open(IMAGES_SENT_DB, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    """Save the transmission state to a file."""
    with open(IMAGES_SENT_DB, 'w') as f:
        json.dump(state, f)

def send_image_data_in_chunks(nCard, b64_image, image_dhash, chunk_size=CHUNK_SIZE, timeout_secs=TIMEOUT_SECS):
    """Send image data to Notecard in chunks with retries for each chunk."""
    state = load_state()
    last_sent_chunk = state.get(image_dhash, -1)
    iter_list = list(chunk_data(b64_image, chunk_size))
    chunk_total = len(iter_list)
    for chunk_index, chunk in enumerate(chunk_data(b64_image, chunk_size)):
        
        if chunk_index < last_sent_chunk:
            print(f"Skipping already sent chunk {chunk_index}.")
            continue  # Skip chunks that have been sent successfully

        success = False
        for attempt in range(CHUNK_RETRIES):
            try:
                print(f"Sending chunk {chunk_index}, attempt {attempt + 1}...")
                req = {
                    "req": "note.add",
                    "body": 
                    {       
                        "img_dhash": image_dhash,
                        "chunk_index": chunk_index,
                        "b64_img_chunk": chunk,
                        "b64_chunk_total": chunk_total
                    },
                    "seconds": timeout_secs
                }
                rsp = nCard.Transaction(req)
                if 'err' in rsp:
                    print(f"Error in Notecard response for chunk {chunk_index}: {rsp['err']}")
                else:
                    print(f"Chunk {chunk_index} sent successfully.")
                    state[image_dhash] = chunk_index
                    save_state(state)
                    success = True
                    if 'total' in rsp:
                        if rsp['total'] > 50:
                            sync_notecard(nCard)

                    break  # Exit retry loop if successful
            except Exception as e:
                print(f"Exception during attempt {attempt + 1} for chunk {chunk_index}:")
                handle_exception(e)
        if not success:
            print(f"Failed to send chunk {chunk_index} after {CHUNK_RETRIES} attempts.")
            return False
    return True


def send_image_with_retries(nCard, image_path, image_dhash, retries=CHUNK_RETRIES):
    """Send image data with retries for failed chunks."""
    b64_image = encode_image_to_base64(image_path)
    for attempt in range(retries):
        print(f"Attempt {attempt + 1} to send image data...")
        if send_image_data_in_chunks(nCard, b64_image, image_dhash):
            print("Image data sent successfully.")
            return True
        print(f"Attempt {attempt + 1} failed.")
    print("Failed to send image data after multiple attempts.")
    return False


def send_image_cell_data(nCard, img_dhash):
    # Compress image before sending
    compress_image(f"./{img_dhash}.png", f"./{img_dhash}.jpeg", 60, 4)
    
    if send_image_with_retries(nCard, f"./{img_dhash}.jpeg", img_dhash):
        # Sync with the Notecard after sending the image
        sync_notecard(nCard)
    else:
        print("Failed to send image data.")

    
def logic_thread(nCard):
    last_reference_time = time.time()
    last_send_time = time.time()
    reference_image, reference_dhash = reference_frame_setup()
    send_interval = 60  # Interval in seconds to send image data

    while True:
        current_image = capture_image()
        if current_image:
            current_dhash = imagehash.dhash(current_image)

            # Check if significant movement has been detected
            movement_infront_of_camera, hamming_distance = cam_movement(3, current_image, current_dhash, reference_dhash)
            movement_infront_of_pir_sensor = pir_movement(PIR_PIN)

            if movement_infront_of_camera or movement_infront_of_pir_sensor:
                # Save the image locally
                current_image.save(f"./{current_dhash}.png")

                # Put a task in the queue for the network thread to process
                task_queue.put({
                    'type': 'send_metadata',
                    'c_dhash': current_dhash,
                    'h_distance': hamming_distance,
                    'c_movement': movement_infront_of_camera,
                    'pir_movement': movement_infront_of_pir_sensor
                })

            # Periodically queue up a task to send image data
            if time.time() - last_send_time > send_interval:
                task_queue.put({
                    'type': 'check_for_requests'
                })
                last_send_time = time.time()

            # Update reference image every interval
            if time.time() - last_reference_time > 15:
                reference_image, reference_dhash = reference_frame_setup()
                last_reference_time = time.time()

        time.sleep(1)

def get_gps(nCard):
    req = {"req": "card.location"}
    # req = add_crc_to_request(req)  # Add CRC to the request
    rsp = nCard.Transaction(req)
    print(rsp)
    coords = {"lat": 0.0, "lon": 0.0}
    if "lat" in rsp and "lon" in rsp:
        coords["lat"] = rsp["lat"]
        coords["lon"] = rsp["lon"]
    return coords

def reference_frame_setup():
    ref_image = capture_image()
    if ref_image is not None:
        return ref_image, imagehash.dhash(ref_image)
    else:
        return None, None

def convert_to_plus_code(latitude, longitude):
    return pluscodes.encode(latitude, longitude)

def setup_notecarrier():
    global PRODUCT_UID
    try:
        port = I2C("/dev/i2c-1")
        nCard = notecard.OpenI2C(port, 0, 0, debug=True)
        return nCard
    except Exception as e:
        print(f"An error occurred while setting up the Notecard: {e}")
        raise

def setup():
    global PIR_PIN
    print("Setting up device...")
    setup_gpio(PIR_PIN)
    return setup_notecarrier()

if __name__ == "__main__":
    time.sleep(10)  # Add a delay to allow the camera to initialize
    find_correct_CAM_INDEX()

    # Setup notecard carrier
    nCard = setup()

    # Start the networking thread
    network_thread_obj = threading.Thread(target=network_thread, args=(nCard,))
    network_thread_obj.daemon = True
    network_thread_obj.start()

    # Start the logic thread
    logic_thread_obj = threading.Thread(target=logic_thread, args=(nCard,))
    logic_thread_obj.daemon = True
    logic_thread_obj.start()

    # Keep the main thread alive to allow threads to run
    network_thread_obj.join()
    logic_thread_obj.join()
