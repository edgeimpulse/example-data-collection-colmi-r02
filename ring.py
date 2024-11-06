import argparse
import asyncio
import json
import os
import csv
from bleak import BleakClient, BleakScanner
from datetime import datetime

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

# Ensure folder exists
os.makedirs(DATA_FOLDER, exist_ok=True)

# Create filename with current timestamp
timestamp_now = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = os.path.join(DATA_FOLDER, f"ring_data_{timestamp_now}.csv")

# Open CSV file for writing
csv_file = open(filename, mode="w", newline="")
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "timestamp", "payload", "accX", "accY", "accZ",
    "ppg_raw", "ppg_max", "ppg_min", "ppg_diff", "ppg",
    "spO2_raw", "spO2_max", "spO2_min", "spO2_diff"
])

async def handle_notification(sender: int, data: bytearray):

    # Initialize parsed_data dictionary with default empty values
    parsed_data = {
        "payload": "", "accX": "", "accY": "", "accZ": "",
        "ppg_raw": "", "ppg_max": "", "ppg_min": "", "ppg_diff": "", "ppg": "",
        "spO2_raw": "", "spO2_max": "", "spO2_min": "", "spO2_diff": ""
    }
    """Callback to update sensor data and write to CSV every 100ms."""
    # Store the payload as a hex string
    parsed_data["payload"] = data.hex()

    # Update parsed_data based on the sensor type
    # if data[0] == 0x03:
    #     parsed_data["battery_level"] = data[1]
    if data[0] == 0xA1:
        subtype = data[1]
        if subtype == 0x01:
            parsed_data["spO2_raw"] = (data[2] << 8) | data[3]
            parsed_data["spO2_max"] = data[5]
            parsed_data["spO2_min"] = data[7]
            parsed_data["spO2_diff"] = data[9]
        elif subtype == 0x02:
            parsed_data["ppg_raw"] = (data[2] << 8) | data[3]
            parsed_data["ppg_max"] = (data[4] << 8) | data[5]
            parsed_data["ppg_min"] = (data[6] << 8) | data[7]
            parsed_data["ppg_diff"] = (data[8] << 8) | data[9]
        elif subtype == 0x03:
            parsed_data["accX"] = ((data[6] << 4) | (data[7] & 0xF)) - (1 << 11) if data[6] & 0x8 else ((data[6] << 4) | (data[7] & 0xF))
            parsed_data["accY"] = ((data[2] << 4) | (data[3] & 0xF)) - (1 << 11) if data[2] & 0x8 else ((data[2] << 4) | (data[3] & 0xF))
            parsed_data["accZ"] = ((data[4] << 4) | (data[5] & 0xF)) - (1 << 11) if data[4] & 0x8 else ((data[4] << 4) | (data[5] & 0xF))
        
        timestamp = datetime.now().isoformat()
        csv_writer.writerow([timestamp] + [parsed_data.get(col, "") for col in parsed_data])
        print("Written to CSV:", [timestamp] + [parsed_data.get(col, "") for col in parsed_data])  # Confirm write

    # Print parsed data to verify the values
    print("Received data:", parsed_data)

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

async def main(duration):
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

# Entry point with argument parsing
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bluetooth ring data logger")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds to run the logger")
    args = parser.parse_args()

    asyncio.run(main(args.duration))
