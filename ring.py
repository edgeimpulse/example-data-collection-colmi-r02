import argparse
import asyncio
import json
import os
import csv
from bleak import BleakClient, BleakScanner
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import requests

# UUIDs for MAIN and RXTX services and characteristics
MAIN_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
MAIN_WRITE_CHARACTERISTIC_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
MAIN_NOTIFY_CHARACTERISTIC_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
RXTX_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
RXTX_WRITE_CHARACTERISTIC_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
RXTX_NOTIFY_CHARACTERISTIC_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Commands
def create_command(hex_string):
    bytes_array = [int(hex_string[i:i+2], 16) for i in range(0, len(hex_string), 2)]
    while len(bytes_array) < 15:
        bytes_array.append(0)
    checksum = sum(bytes_array) & 0xFF
    bytes_array.append(checksum)
    return bytes(bytes_array)

BATTERY_CMD = create_command("03")
SET_UNITS_METRICS = create_command("0a0200")
ENABLE_RAW_SENSOR_CMD = create_command("a104")
DISABLE_RAW_SENSOR_CMD = create_command("a102")

CONFIG_FILE = "config.json"
DATA_FOLDER = "raw_data"
INGESTION_URL = "https://ingestion.edgeimpulse.com"  # Base URL for ingestion

# Ensure folder exists
os.makedirs(DATA_FOLDER, exist_ok=True)

# Create filename with current timestamp
timestamp_now = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = os.path.join(DATA_FOLDER, f"ring_data_{timestamp_now}.csv")

# Utils functions 

def resample_data(input_file, resample_ms, columns, output_path=None):
    """Resample the data to a specified frequency in milliseconds and optionally save the result."""
    frequency = f'{resample_ms}ms'

    # Load data and ensure timestamp is in datetime format
    df = pd.read_csv(input_file, parse_dates=['timestamp'])
    df = df.set_index('timestamp')

    # Select only the desired columns and resample
    df_resampled = df[columns].resample(frequency).mean().interpolate(method='linear')

    # Reset the index to make 'timestamp' a column again
    df_resampled = df_resampled.reset_index()

    # Save the resampled data to a CSV file if output_path is provided
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_resampled.to_csv(output_path, index=False)
        print(f"Resampled data saved to {output_path}")

    return df_resampled

def plot_data(df, columns, filename, label=None):
    """Plot specified columns from DataFrame and save graphs."""
    # Create a folder for graphs if it doesn't exist
    os.makedirs("graphs", exist_ok=True)

    # Strip the .csv extension from filename
    base_filename = os.path.splitext(os.path.basename(filename))[0]
    if label:
        base_filename = f"{label}.{base_filename}"

    for column in columns:
        plt.figure(figsize=(10, 6))
        plt.plot(df['timestamp'], df[column], label=column, color='b')
        plt.title(f"{column} over Time")
        plt.xlabel("Timestamp")
        plt.ylabel(column)
        plt.xticks(rotation=45)
        plt.legend()
        plt.tight_layout()

        # Define the output path with the optional label
        output_path = f"graphs/{base_filename}_{column}.png"
        
        plt.savefig(output_path)
        print(f"Graph saved to {output_path}")
        plt.close()

def load_config():
    """Load configuration from config.json."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as file:
            return json.load(file)
    return {}

def save_config(config):
    """Save configuration to config.json."""
    with open(CONFIG_FILE, "w") as file:
        json.dump(config, file, indent=4)

def load_api_key():
    """Load API key from config.json."""
    config = load_config()
    return config.get("EI_API_KEY")

def save_api_key(api_key):
    """Save API key to config.json."""
    config = load_config()
    config["EI_API_KEY"] = api_key
    save_config(config)

def upload_to_edge_impulse(fullpath, label, api_key, category="training", metadata=None):
    """
    Upload a CSV file to Edge Impulse ingestion service.

    :param fullpath: Path to the CSV file to upload.
    :param label: Label for the uploaded data.
    :param api_key: Edge Impulse API key for authorization.
    :param category: Category for the data (e.g., "training", "testing").
    """
    upload_url = f"{INGESTION_URL}/api/{category}/files"
   

    # Prepare the request headers and metadata
    headers = {
        'x-label': label,
        'x-api-key': api_key,
        'x-metadata': json.dumps(metadata),
    }

    # Open the CSV file and upload it
    with open(fullpath, 'rb') as csv_file:
        files = { 'data': (os.path.basename(fullpath), csv_file, 'text/csv') }
        res = requests.post(url=upload_url, headers=headers, files=files)

    # Check the response
    if res.status_code == 200:
        print("Data successfully uploaded to Edge Impulse.")
    else:
        print(f"Failed to upload data: {res.status_code} - {res.text}")

# Open CSV file for writing
csv_file = open(filename, mode="w", newline="")
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "timestamp", "payload", "accX", "accY", "accZ",
    "ppg", "ppg_max", "ppg_min", "ppg_diff",
    "spO2", "spO2_max", "spO2_min", "spO2_diff"
])

async def handle_notification(sender: int, data: bytearray):

    # Initialize parsed_data dictionary with default empty values
    parsed_data = {
        "payload": "", "accX": "", "accY": "", "accZ": "",
        "ppg": "", "ppg_max": "", "ppg_min": "", "ppg_diff": "",
        "spO2": "", "spO2_max": "", "spO2_min": "", "spO2_diff": ""
    }
    
    # Store the payload as a hex string
    parsed_data["payload"] = data.hex()

    # Update parsed_data based on the sensor type
    if data[0] == 0xA1:
        subtype = data[1]
        if subtype == 0x01:
            parsed_data["spO2"] = (data[2] << 8) | data[3]
            parsed_data["spO2_max"] = data[5]
            parsed_data["spO2_min"] = data[7]
            parsed_data["spO2_diff"] = data[9]
        elif subtype == 0x02:
            parsed_data["ppg"] = (data[2] << 8) | data[3]
            parsed_data["ppg_max"] = (data[4] << 8) | data[5]
            parsed_data["ppg_min"] = (data[6] << 8) | data[7]
            parsed_data["ppg_diff"] = (data[8] << 8) | data[9]
        elif subtype == 0x03:
            parsed_data["accX"] = ((data[6] << 4) | (data[7] & 0xF)) - (1 << 11) if data[6] & 0x8 else ((data[6] << 4) | (data[7] & 0xF))
            parsed_data["accY"] = ((data[2] << 4) | (data[3] & 0xF)) - (1 << 11) if data[2] & 0x8 else ((data[2] << 4) | (data[3] & 0xF))
            parsed_data["accZ"] = ((data[4] << 4) | (data[5] & 0xF)) - (1 << 11) if data[4] & 0x8 else ((data[4] << 4) | (data[5] & 0xF))
        
        # Check if ppg and spO2 are equal to zero; skip writing if true
        if parsed_data["ppg"] == 0 or parsed_data["spO2"] == 0:
            print("Skipping data with zero ppg and spO2 values")
            return

        timestamp = datetime.now().isoformat()
        csv_writer.writerow([timestamp] + [parsed_data.get(col, "") for col in parsed_data])
        print("Written to CSV:", [timestamp] + [parsed_data.get(col, "") for col in parsed_data])  # Confirm write

    # Print parsed data to verify the values
    # print("Received data:", parsed_data)

async def send_data_array(client, command, service_name):
    """Send data to RXTX or MAIN service's write characteristic."""
    try:
        if service_name == "MAIN":
            await client.write_gatt_char(MAIN_WRITE_CHARACTERISTIC_UUID, command)
        elif service_name == "RXTX":
            await client.write_gatt_char(RXTX_WRITE_CHARACTERISTIC_UUID, command)
    except Exception as e:
        print(f"Failed to send data to {service_name} service: {e}")

def load_device_address():
    """Load saved device address from config file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)
            return config.get("device_address")
    return None

def save_device_address(address):
    """Save the device address to config file."""
    with open(CONFIG_FILE, "w") as file:
        json.dump({"device_address": address}, file)

async def select_device():
    """Scan for available Bluetooth devices and allow the user to select one."""
    devices = await BleakScanner.discover()
    for i, device in enumerate(devices):
        print(f"{i}: {device.name} [{device.address}]")
    if devices:
        choice = int(input("Select a device by entering its number: "))
        return devices[choice]
    return None

# Main
async def main(duration, label, columns, resample_ms, plot, ei_upload):
    """Main function with specified duration (seconds) for the reading."""
    device_address = load_device_address()
    if not device_address:
        selected_device = await select_device()
        if not selected_device:
            print("No device selected. Exiting...")
            return
        device_address = selected_device.address
        save_device_address(device_address)

    async with BleakClient(device_address) as client:
        if not client.is_connected:
            print("Failed to connect to the device.")
            return

        print(f"Connected to device with address {device_address}!")

        await client.start_notify(MAIN_NOTIFY_CHARACTERISTIC_UUID, handle_notification)
        await client.start_notify(RXTX_NOTIFY_CHARACTERISTIC_UUID, handle_notification)

        await asyncio.sleep(2)  # Ensure notifications are set up

        await send_data_array(client, BATTERY_CMD, "RXTX")
        await send_data_array(client, SET_UNITS_METRICS, "RXTX")
        await send_data_array(client, ENABLE_RAW_SENSOR_CMD, "RXTX")

        try:
            await asyncio.sleep(duration)  # Keep running for the specified duration
        finally:
            await send_data_array(client, DISABLE_RAW_SENSOR_CMD, "RXTX")
            csv_file.close()
            print(f"Data saved to {filename}")

            if resample_ms:
                resampled_output_path = os.path.join("resampled", f"{label}.{os.path.basename(filename)}") if label else f"resampled/{os.path.basename(filename)}"
                df_resampled = resample_data(filename, resample_ms, columns, output_path=resampled_output_path)

                if plot:
                    plot_data(df_resampled, columns, filename, label)

                if ei_upload:
                    metadata = {
                        "timestamp": timestamp_now,
                        "source": "Colmi Ring R02"
                    }
                    api_key = load_api_key()
                    if not api_key:
                        api_key = input("Please enter your Edge Impulse API Key: ")
                        save_api_key(api_key)
                    upload_to_edge_impulse(resampled_output_path, label or "unlabeled", api_key, metadata=metadata) 

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bluetooth ring data logger")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds to run the logger")
    parser.add_argument("--label", type=str, help="Label for the dataset")
    parser.add_argument("--axis", type=str, help="Columns to include in resampling and plotting, separated by commas")
    parser.add_argument("--resample", type=int, default=20, help="Resampling rate in milliseconds")
    parser.add_argument("--plot", action="store_true", help="Plot the selected columns")
    parser.add_argument("--ei_upload", action="store_true", help="Upload the data to Edge Impulse")

    args = parser.parse_args()
    columns = args.axis.split(",") if args.axis else ["accX", "accY", "accZ", "ppg", "spO2"]

    asyncio.run(main(args.duration, args.label, columns, args.resample, args.plot, args.ei_upload))
