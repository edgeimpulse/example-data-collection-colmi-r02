import asyncio
import csv
import json
import os
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import pandas as pd
import requests
from bleak import BleakClient, BleakScanner
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

MAIN_NOTIFY_CHARACTERISTIC_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
RXTX_NOTIFY_CHARACTERISTIC_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
RXTX_WRITE_CHARACTERISTIC_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

INGESTION_URL = "https://ingestion.edgeimpulse.com"
CONFIG_FILE = Path("config.json")
RAW_FOLDER = Path("raw_data")
RESAMPLED_FOLDER = Path("resampled")
MAX_POINTS = 1200


def create_command(hex_string: str) -> bytes:
    bytes_array = [int(hex_string[i : i + 2], 16) for i in range(0, len(hex_string), 2)]
    while len(bytes_array) < 15:
        bytes_array.append(0)
    checksum = sum(bytes_array) & 0xFF
    bytes_array.append(checksum)
    return bytes(bytes_array)


BATTERY_CMD = create_command("03")
SET_UNITS_METRICS = create_command("0a0200")
ENABLE_RAW_SENSOR_CMD = create_command("a104")
DISABLE_RAW_SENSOR_CMD = create_command("a102")


class StartRequest(BaseModel):
    duration: int = Field(default=60, ge=10, le=3600)
    label: str = Field(default="activity", min_length=1, max_length=100)
    resample_ms: int = Field(default=20, ge=10, le=200)
    selected_address: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    gender: str = Field(default="unspecified")
    age: int = Field(default=30, ge=1, le=120)
    country: str = Field(default="")
    auto_upload: bool = Field(default=False)
    api_key: Optional[str] = None


class UploadRequest(BaseModel):
    api_key: str = Field(min_length=1)
    label: Optional[str] = None
    patient_id: str = Field(min_length=1)
    gender: str = Field(default="unspecified")
    age: int = Field(default=30, ge=1, le=120)
    country: str = Field(default="")


class UploadRawFileRequest(BaseModel):
    file_name: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    label: Optional[str] = None
    patient_id: str = Field(min_length=1)
    gender: str = Field(default="unspecified")
    age: int = Field(default=30, ge=1, le=120)
    country: str = Field(default="")
    upload_mode: str = Field(default="raw")
    acc_hz: Optional[float] = Field(default=None, gt=0)
    ppg_hz: Optional[float] = Field(default=None, gt=0)
    spo2_hz: Optional[float] = Field(default=None, gt=0)


@dataclass
class LiveSeries:
    timestamps: Deque[str] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    acc_x: Deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    acc_y: Deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    acc_z: Deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    ppg: Deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    spo2: Deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))


@dataclass
class RecorderState:
    is_running: bool = False
    stop_event: Optional[threading.Event] = None
    thread: Optional[threading.Thread] = None
    queue: "queue.Queue[Dict[str, Any]]" = field(default_factory=queue.Queue)
    csv_path: Optional[Path] = None
    resampled_path: Optional[Path] = None
    label: str = "activity"
    error: Optional[str] = None


class Hub:
    def __init__(self) -> None:
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        disconnected: List[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


recorder = RecorderState()
live = LiveSeries()
hub = Hub()

app = FastAPI(title="R02 Activity Collector")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/docs", StaticFiles(directory="docs"), name="docs")
templates = Jinja2Templates(directory="templates")


def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def save_device_address(address: str) -> None:
    config = load_config()
    config["device_address"] = address
    save_config(config)


def load_device_address() -> Optional[str]:
    return load_config().get("device_address")


def load_api_key() -> Optional[str]:
    return load_config().get("EI_API_KEY")


def save_api_key(api_key: str) -> None:
    config = load_config()
    config["EI_API_KEY"] = api_key
    save_config(config)


def parse_packet(data: bytearray) -> Dict[str, Any]:
    parsed_data = {
        "payload": data.hex(),
        "accX": "",
        "accY": "",
        "accZ": "",
        "ppg": "",
        "ppg_max": "",
        "ppg_min": "",
        "ppg_diff": "",
        "spO2": "",
        "spO2_max": "",
        "spO2_min": "",
        "spO2_diff": "",
    }

    if not data or data[0] != 0xA1:
        return parsed_data

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
        parsed_data["accX"] = (
            ((data[6] << 4) | (data[7] & 0xF)) - (1 << 11)
            if data[6] & 0x8
            else ((data[6] << 4) | (data[7] & 0xF))
        )
        parsed_data["accY"] = (
            ((data[2] << 4) | (data[3] & 0xF)) - (1 << 11)
            if data[2] & 0x8
            else ((data[2] << 4) | (data[3] & 0xF))
        )
        parsed_data["accZ"] = (
            ((data[4] << 4) | (data[5] & 0xF)) - (1 << 11)
            if data[4] & 0x8
            else ((data[4] << 4) | (data[5] & 0xF))
        )

    return parsed_data


def upload_to_edge_impulse_json(
    data: Dict[str, Any],
    file_name: str,
    label: str,
    api_key: str,
    metadata: Dict[str, Any],
) -> requests.Response:
    upload_url = f"{INGESTION_URL}/api/training/data"
    headers = {
        "x-file-name": file_name,
        "x-label": label,
        "x-api-key": api_key,
        "x-metadata": json.dumps(metadata),
        "Content-Type": "application/json",
    }
    return requests.post(url=upload_url, headers=headers, json=data, timeout=30)


def _median_interval_ms(timestamps: pd.Series) -> float:
    ts = pd.to_datetime(timestamps, errors="coerce").dropna()
    if len(ts) < 2:
        return 20.0
    diffs = ts.diff().dropna().dt.total_seconds() * 1000
    if diffs.empty:
        return 20.0
    return float(diffs.median())


def stringify_metadata(metadata: Dict[str, Any]) -> Dict[str, str]:
    return {k: "" if v is None else str(v) for k, v in metadata.items()}


def _series_frequency_hz(timestamps: pd.Series) -> Optional[float]:
    ts = pd.to_datetime(timestamps, errors="coerce").dropna()
    if len(ts) < 2:
        return None
    diffs = ts.diff().dropna().dt.total_seconds()
    if diffs.empty:
        return None
    median_sec = float(diffs.median())
    if median_sec <= 0:
        return None
    return 1.0 / median_sec


def summarize_raw_csv(path: Path) -> Dict[str, Any]:
    df = pd.read_csv(path)
    rows = len(df)
    if "timestamp" not in df.columns:
        return {
            "file_name": path.name,
            "rows": rows,
            "acc_hz": None,
            "ppg_hz": None,
            "spo2_hz": None,
        }

    if "spO2" not in df.columns and "spo2" in df.columns:
        df = df.rename(columns={"spo2": "spO2"})

    summary: Dict[str, Any] = {
        "file_name": path.name,
        "rows": rows,
        "acc_hz": None,
        "ppg_hz": None,
        "spo2_hz": None,
    }

    if all(col in df.columns for col in ["accX", "accY", "accZ"]):
        acc_ts = df.dropna(subset=["accX", "accY", "accZ"], how="any")["timestamp"]
        summary["acc_hz"] = _series_frequency_hz(acc_ts)

    if "ppg" in df.columns:
        ppg_ts = df[(df["ppg"].notna()) & (df["ppg"] != 0)]["timestamp"]
        summary["ppg_hz"] = _series_frequency_hz(ppg_ts)

    if "spO2" in df.columns:
        spo2_ts = df[(df["spO2"].notna()) & (df["spO2"] != 0)]["timestamp"]
        summary["spo2_hz"] = _series_frequency_hz(spo2_ts)

    return summary


def resolve_raw_file(file_name: str) -> Path:
    safe_name = Path(file_name).name
    path = RAW_FOLDER / safe_name
    if path.suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw dataset not found")
    return path


def load_raw_series(path: Path) -> Dict[str, Any]:
    df = pd.read_csv(path)
    if "spO2" not in df.columns and "spo2" in df.columns:
        df = df.rename(columns={"spo2": "spO2"})

    for col in ["accX", "accY", "accZ", "ppg", "spO2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "timestamp" not in df.columns:
        raise ValueError("Missing timestamp column in dataset")

    if "ppg" in df.columns:
        df.loc[df["ppg"] == 0, "ppg"] = pd.NA
    if "spO2" in df.columns:
        df.loc[df["spO2"] == 0, "spO2"] = pd.NA

    ts = pd.to_datetime(df["timestamp"], errors="coerce")

    return {
        "timestamps": [t.isoformat() if pd.notna(t) else None for t in ts],
        "accX": df["accX"].where(df["accX"].notna(), None).tolist() if "accX" in df.columns else [],
        "accY": df["accY"].where(df["accY"].notna(), None).tolist() if "accY" in df.columns else [],
        "accZ": df["accZ"].where(df["accZ"].notna(), None).tolist() if "accZ" in df.columns else [],
        "ppg": df["ppg"].where(df["ppg"].notna(), None).tolist() if "ppg" in df.columns else [],
        "spO2": df["spO2"].where(df["spO2"].notna(), None).tolist() if "spO2" in df.columns else [],
    }


def _build_payload_from_df(df: pd.DataFrame, sensor_cols: List[str], interval_ms: Optional[float]) -> Optional[Dict[str, Any]]:
    if not all(col in df.columns for col in sensor_cols):
        return None

    part = df.dropna(subset=sensor_cols, how="any")[["timestamp", *sensor_cols]].copy()
    if sensor_cols == ["ppg"]:
        part = part[part["ppg"] != 0]
    if sensor_cols == ["spO2"]:
        part = part[part["spO2"] != 0]
    if part.empty:
        return None

    part["timestamp"] = pd.to_datetime(part["timestamp"], errors="coerce")
    part = part.dropna(subset=["timestamp"])
    if part.empty:
        return None

    if interval_ms and interval_ms > 0:
        part = part.set_index("timestamp")[sensor_cols].resample(f"{interval_ms}ms").mean().interpolate(method="time")
        part = part.dropna(how="any").reset_index()
        if part.empty:
            return None
        out_interval_ms = float(interval_ms)
    else:
        out_interval_ms = _median_interval_ms(part["timestamp"])

    return {
        "sensors": [{"name": col, "units": "N/A"} for col in sensor_cols],
        "interval_ms": out_interval_ms,
        "values": part[sensor_cols].values.tolist(),
    }


def prepare_edge_impulse_json_resampled(
    input_file: Path,
    acc_hz: Optional[float],
    ppg_hz: Optional[float],
    spo2_hz: Optional[float],
) -> Dict[str, Any]:
    df = pd.read_csv(input_file)
    if "timestamp" not in df.columns:
        raise ValueError("Missing timestamp column in dataset")
    if "spO2" not in df.columns and "spo2" in df.columns:
        df = df.rename(columns={"spo2": "spO2"})
    for col in ["accX", "accY", "accZ", "ppg", "spO2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    acc_interval = (1000.0 / acc_hz) if acc_hz else None
    ppg_interval = (1000.0 / ppg_hz) if ppg_hz else None
    spo2_interval = (1000.0 / spo2_hz) if spo2_hz else None

    payloads: List[Dict[str, Any]] = []
    acc_payload = _build_payload_from_df(df, ["accX", "accY", "accZ"], acc_interval)
    ppg_payload = _build_payload_from_df(df, ["ppg"], ppg_interval)
    spo2_payload = _build_payload_from_df(df, ["spO2"], spo2_interval)

    for payload in [acc_payload, ppg_payload, spo2_payload]:
        if payload:
            payloads.append(payload)

    if not payloads:
        raise ValueError("No valid sensor rows to upload")

    return {
        "protected": {
            "ver": "v1",
            "alg": "HS256",
            "iat": int(datetime.now().timestamp()),
        },
        "signature": "0" * 64,
        "payloads": payloads,
    }


def resample_data(input_file: Path, resample_ms: int) -> pd.DataFrame:
    frequency = f"{resample_ms}ms"
    df = pd.read_csv(input_file, parse_dates=["timestamp"]).set_index("timestamp")
    df_resampled = (
        df[["accX", "accY", "accZ", "ppg", "spO2"]]
        .apply(pd.to_numeric, errors="coerce")
        .resample(frequency)
        .mean()
        .interpolate(method="linear")
        .reset_index()
    )
    return df_resampled


def prepare_edge_impulse_json(input_file: Path) -> Dict[str, Any]:
    df = pd.read_csv(input_file)
    if "timestamp" not in df.columns:
        raise ValueError("Missing timestamp column in dataset")

    if "spO2" not in df.columns and "spo2" in df.columns:
        df = df.rename(columns={"spo2": "spO2"})

    for col in ["accX", "accY", "accZ", "ppg", "spO2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Build independent payload streams so each signal family can keep its own sampling interval.
    acc_df = (
        df.dropna(subset=["accX", "accY", "accZ"], how="any")
        if all(col in df.columns for col in ["accX", "accY", "accZ"])
        else pd.DataFrame()
    )
    ppg_df = df.dropna(subset=["ppg"], how="any") if "ppg" in df.columns else pd.DataFrame()
    spo2_df = df.dropna(subset=["spO2"], how="any") if "spO2" in df.columns else pd.DataFrame()
    if not ppg_df.empty:
        ppg_df = ppg_df[ppg_df["ppg"] != 0]
    if not spo2_df.empty:
        spo2_df = spo2_df[spo2_df["spO2"] != 0]

    payloads: List[Dict[str, Any]] = []

    if not acc_df.empty:
        payloads.append(
            {
                "sensors": [
                    {"name": "accX", "units": "N/A"},
                    {"name": "accY", "units": "N/A"},
                    {"name": "accZ", "units": "N/A"},
                ],
                "interval_ms": _median_interval_ms(acc_df["timestamp"]),
                "values": acc_df[["accX", "accY", "accZ"]].values.tolist(),
            }
        )

    if not ppg_df.empty:
        payloads.append(
            {
                "sensors": [{"name": "ppg", "units": "N/A"}],
                "interval_ms": _median_interval_ms(ppg_df["timestamp"]),
                "values": ppg_df[["ppg"]].values.tolist(),
            }
        )

    if not spo2_df.empty:
        payloads.append(
            {
                "sensors": [{"name": "spO2", "units": "N/A"}],
                "interval_ms": _median_interval_ms(spo2_df["timestamp"]),
                "values": spo2_df[["spO2"]].values.tolist(),
            }
        )

    if not payloads:
        raise ValueError("No valid sensor rows to upload")

    return {
        "protected": {
            "ver": "v1",
            "alg": "HS256",
            "iat": int(datetime.now().timestamp()),
        },
        "signature": "0" * 64,
        "payloads": payloads,
    }


class RingRecorder:
    def __init__(self, event_queue: "queue.Queue[Dict[str, Any]]") -> None:
        self.event_queue = event_queue

    async def send_data_array(self, client: BleakClient, command: bytes) -> None:
        await client.write_gatt_char(RXTX_WRITE_CHARACTERISTIC_UUID, command)

    async def run(self, req: StartRequest, stop_event: threading.Event) -> None:
        RAW_FOLDER.mkdir(exist_ok=True)
        RESAMPLED_FOLDER.mkdir(exist_ok=True)

        timestamp_now = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = RAW_FOLDER / f"{req.label}.ring_data_{timestamp_now}.csv"

        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "timestamp",
                    "payload",
                    "accX",
                    "accY",
                    "accZ",
                    "ppg",
                    "ppg_max",
                    "ppg_min",
                    "ppg_diff",
                    "spO2",
                    "spO2_max",
                    "spO2_min",
                    "spO2_diff",
                ]
            )

            def on_notification(_: int, data: bytearray) -> None:
                parsed = parse_packet(data)
                if parsed.get("ppg") == 0 or parsed.get("spO2") == 0:
                    return
                ts = datetime.now().isoformat()
                row = [
                    ts,
                    parsed.get("payload", ""),
                    parsed.get("accX", ""),
                    parsed.get("accY", ""),
                    parsed.get("accZ", ""),
                    parsed.get("ppg", ""),
                    parsed.get("ppg_max", ""),
                    parsed.get("ppg_min", ""),
                    parsed.get("ppg_diff", ""),
                    parsed.get("spO2", ""),
                    parsed.get("spO2_max", ""),
                    parsed.get("spO2_min", ""),
                    parsed.get("spO2_diff", ""),
                ]
                writer.writerow(row)
                self.event_queue.put(
                    {
                        "type": "data",
                        "timestamp": ts,
                        "accX": parsed.get("accX"),
                        "accY": parsed.get("accY"),
                        "accZ": parsed.get("accZ"),
                        "ppg": parsed.get("ppg"),
                        "spO2": parsed.get("spO2"),
                    }
                )

            async with BleakClient(req.selected_address) as client:
                if not client.is_connected:
                    raise RuntimeError("Failed to connect to selected ring")

                await client.start_notify(MAIN_NOTIFY_CHARACTERISTIC_UUID, on_notification)
                await client.start_notify(RXTX_NOTIFY_CHARACTERISTIC_UUID, on_notification)
                await asyncio.sleep(1)

                await self.send_data_array(client, BATTERY_CMD)
                await self.send_data_array(client, SET_UNITS_METRICS)
                await self.send_data_array(client, ENABLE_RAW_SENSOR_CMD)

                started = datetime.now()
                try:
                    while (datetime.now() - started).total_seconds() < req.duration:
                        if stop_event.is_set():
                            break
                        await asyncio.sleep(0.1)
                finally:
                    await self.send_data_array(client, DISABLE_RAW_SENSOR_CMD)

        event: Dict[str, Any] = {
            "type": "finished",
            "csv_path": str(csv_path),
            "resampled_path": None,
            "label": req.label,
        }

        if req.auto_upload:
            api_key = (req.api_key or load_api_key() or "").strip()
            if not api_key:
                event["upload_status"] = "Auto-upload skipped: API key is empty"
            else:
                save_api_key(api_key)
                timestamp_now_iso = datetime.now().isoformat()
                metadata = {
                    "timestamp": timestamp_now_iso,
                    "source": "Colmi Ring R02",
                    "patient_id": req.patient_id,
                    "gender": req.gender,
                    "age": req.age,
                    "country": req.country,
                }
                try:
                    ei_json = prepare_edge_impulse_json(csv_path)
                    response = upload_to_edge_impulse_json(
                        ei_json,
                        f"{csv_path.stem}.json",
                        req.label,
                        api_key,
                        stringify_metadata(metadata),
                    )
                    if response.status_code == 200:
                        event["upload_status"] = "Auto-upload successful"
                    else:
                        event["upload_status"] = f"Auto-upload failed: {response.status_code} {response.text}"
                except Exception as exc:
                    event["upload_status"] = f"Auto-upload failed: {exc}"

        self.event_queue.put(event)


def run_recorder_thread(req: StartRequest, stop_event: threading.Event) -> None:
    local_recorder = RingRecorder(recorder.queue)
    try:
        asyncio.run(local_recorder.run(req, stop_event))
    except Exception as exc:
        recorder.queue.put({"type": "error", "message": str(exc)})


def reset_live_series() -> None:
    live.timestamps.clear()
    live.acc_x.clear()
    live.acc_y.clear()
    live.acc_z.clear()
    live.ppg.clear()
    live.spo2.clear()


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(event_pump())


async def event_pump() -> None:
    while True:
        drained = False
        while True:
            try:
                evt = recorder.queue.get_nowait()
            except queue.Empty:
                break

            drained = True
            if evt["type"] == "data":
                live.timestamps.append(evt["timestamp"])
                live.acc_x.append(evt["accX"] if evt.get("accX") != "" else None)
                live.acc_y.append(evt["accY"] if evt.get("accY") != "" else None)
                live.acc_z.append(evt["accZ"] if evt.get("accZ") != "" else None)
                live.ppg.append(evt["ppg"] if evt.get("ppg") != "" else None)
                live.spo2.append(evt["spO2"] if evt.get("spO2") != "" else None)

            if evt["type"] == "finished":
                recorder.is_running = False
                recorder.csv_path = Path(evt["csv_path"])
                recorder.resampled_path = Path(evt["resampled_path"]) if evt.get("resampled_path") else None
                recorder.label = evt.get("label", recorder.label)

            if evt["type"] == "error":
                recorder.is_running = False
                recorder.error = evt["message"]

            await hub.broadcast(evt)

        await asyncio.sleep(0.03 if drained else 0.08)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    return {
        "is_running": recorder.is_running,
        "error": recorder.error,
        "csv_path": str(recorder.csv_path) if recorder.csv_path else None,
        "resampled_path": str(recorder.resampled_path) if recorder.resampled_path else None,
        "saved_device_address": load_device_address(),
        "saved_api_key": load_api_key() or "",
        "live": {
            "timestamps": list(live.timestamps),
            "accX": list(live.acc_x),
            "accY": list(live.acc_y),
            "accZ": list(live.acc_z),
            "ppg": list(live.ppg),
            "spO2": list(live.spo2),
        },
    }


@app.get("/api/devices")
async def scan_devices() -> Dict[str, Any]:
    devices = await BleakScanner.discover()
    result = [{"name": d.name or "Unnamed", "address": d.address} for d in devices]
    return {"devices": result}


@app.post("/api/device")
async def save_device(payload: Dict[str, str]) -> Dict[str, str]:
    address = payload.get("address", "").strip()
    api_key = payload.get("api_key", "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="Missing device address")
    save_device_address(address)
    if api_key:
        save_api_key(api_key)
    return {"status": "ok"}


@app.post("/api/start")
async def start_recording(req: StartRequest) -> Dict[str, Any]:
    if recorder.is_running:
        raise HTTPException(status_code=409, detail="A recording is already running")

    recorder.error = None
    recorder.is_running = True
    recorder.stop_event = threading.Event()
    reset_live_series()

    recorder.thread = threading.Thread(
        target=run_recorder_thread,
        args=(req, recorder.stop_event),
        daemon=True,
    )
    recorder.thread.start()

    return {"status": "started"}


@app.post("/api/stop")
async def stop_recording() -> Dict[str, Any]:
    if recorder.stop_event:
        recorder.stop_event.set()
    return {"status": "stopping"}


@app.post("/api/upload")
async def upload_latest(req: UploadRequest) -> Dict[str, Any]:
    if not recorder.csv_path or not recorder.csv_path.exists():
        raise HTTPException(status_code=404, detail="No dataset available")

    label = req.label or recorder.label
    api_key = (req.api_key or load_api_key() or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing Edge Impulse API key")
    save_api_key(api_key)

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "source": "Colmi Ring R02",
        "patient_id": req.patient_id,
        "gender": req.gender,
        "age": req.age,
        "country": req.country,
    }
    try:
        ei_json = prepare_edge_impulse_json(recorder.csv_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not prepare Edge Impulse JSON: {exc}") from exc

    response = upload_to_edge_impulse_json(
        ei_json,
        f"{recorder.csv_path.stem}.json",
        label,
        api_key,
        stringify_metadata(metadata),
    )
    if response.status_code == 200:
        return {"status": "ok", "message": "Upload successful"}

    raise HTTPException(status_code=500, detail=f"Upload failed: {response.status_code} {response.text}")


@app.get("/api/raw-files")
async def list_raw_files() -> Dict[str, Any]:
    RAW_FOLDER.mkdir(exist_ok=True)
    files = sorted(RAW_FOLDER.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    items: List[Dict[str, Any]] = []
    for path in files:
        try:
            summary = summarize_raw_csv(path)
        except Exception:
            summary = {
                "file_name": path.name,
                "rows": None,
                "acc_hz": None,
                "ppg_hz": None,
                "spo2_hz": None,
            }
        summary["modified_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        items.append(summary)
    return {"files": items}


@app.get("/api/raw-file")
async def get_raw_file_data(file_name: str) -> Dict[str, Any]:
    path = resolve_raw_file(file_name)
    try:
        series = load_raw_series(path)
        summary = summarize_raw_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read raw dataset: {exc}") from exc

    return {
        "file_name": path.name,
        "rows": summary.get("rows"),
        "frequencies": {
            "acc_hz": summary.get("acc_hz"),
            "ppg_hz": summary.get("ppg_hz"),
            "spo2_hz": summary.get("spo2_hz"),
        },
        "series": series,
    }


@app.post("/api/upload-file")
async def upload_raw_file(req: UploadRawFileRequest) -> Dict[str, Any]:
    csv_path = resolve_raw_file(req.file_name)
    api_key = req.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing Edge Impulse API key")
    save_api_key(api_key)

    label = (req.label or Path(req.file_name).stem.split(".")[0] or "activity").strip()
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "source": "Colmi Ring R02",
        "patient_id": req.patient_id,
        "gender": req.gender,
        "age": req.age,
        "country": req.country,
    }

    upload_mode = (req.upload_mode or "raw").strip().lower()
    if upload_mode not in {"raw", "resampled"}:
        raise HTTPException(status_code=400, detail="upload_mode must be 'raw' or 'resampled'")

    try:
        if upload_mode == "resampled":
            ei_json = prepare_edge_impulse_json_resampled(csv_path, req.acc_hz, req.ppg_hz, req.spo2_hz)
        else:
            ei_json = prepare_edge_impulse_json(csv_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not prepare Edge Impulse JSON: {exc}") from exc

    response = upload_to_edge_impulse_json(
        ei_json,
        f"{csv_path.stem}.json",
        label,
        api_key,
        stringify_metadata(metadata),
    )
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Upload failed: {response.status_code} {response.text}")

    summary = summarize_raw_csv(csv_path)
    return {
        "status": "ok",
        "message": f"Upload successful for {csv_path.name}",
        "file_name": csv_path.name,
        "upload_mode": upload_mode,
        "frequencies": {
            "acc_hz": summary.get("acc_hz"),
            "ppg_hz": summary.get("ppg_hz"),
            "spo2_hz": summary.get("spo2_hz"),
        },
    }


@app.websocket("/ws/live")
async def live_socket(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        await ws.send_json(
            {
                "type": "snapshot",
                "is_running": recorder.is_running,
                "live": {
                    "timestamps": list(live.timestamps),
                    "accX": list(live.acc_x),
                    "accY": list(live.acc_y),
                    "accZ": list(live.acc_z),
                    "ppg": list(live.ppg),
                    "spO2": list(live.spo2),
                },
            }
        )
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8000, reload=False)
