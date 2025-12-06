from pathlib import Path
import yaml
from tqdm import tqdm
import sys
import subprocess
import json
import os
from PIL import Image, UnidentifiedImageError
from math import ceil

def load_monitors(monitor_file: Path):
    if not monitor_file.exists():
        raise FileNotFoundError(f"Monitor file '{monitor_file}' not found.")
    with open(monitor_file) as f:
        return yaml.safe_load(f)

def get_monitor_bounds(monitors, actual_monitor_sizes: bool):
    if actual_monitor_sizes:
        try:
            max_pixels_per_cm_x = max([m["width"]/m["width_cm"] for m in monitors])
            max_pixels_per_cm_y = max([m["height"]/m["height_cm"] for m in monitors])

            min_x = int(min([m["x_cm"] * max_pixels_per_cm_x for m in monitors]))
            min_y = int(min([m["y_cm"]  * max_pixels_per_cm_y for m in monitors]))
            max_x = int(max([(m["x_cm"] + m["width_cm"]) * max_pixels_per_cm_x for m in monitors]))
            max_y = int(max([(m["y_cm"] + m["height_cm"]) * max_pixels_per_cm_y for m in monitors]))
            
            return min_x, min_y, max_x, max_y, max_pixels_per_cm_x, max_pixels_per_cm_y
        except KeyError:
             raise ValueError("In order to use the actual monitor size option, each monitor needs the keys width, height, width_cm, height_cm, x_cm, y_cm")
    else:
        min_x = min([m["x"] for m in monitors])
        min_y = min([m["y"] for m in monitors])
        max_x = max([m["x"] + m["width"] for m in monitors])
        max_y = max([m["y"] + m["height"] for m in monitors])
        
        return min_x, min_y, max_x, max_y, 1, 1

def create_monitor_config(monitor_file: Path, align: str):
    try:
        result = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        # Determine start of JSON array
        json_start = output.find('[')
        if json_start != -1:
            output = output[json_start:]
        monitor_data = json.loads(output)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("Could not run 'hyprctl monitors -j'. Are you using Hyprland?")
    except json.JSONDecodeError:
        raise RuntimeError("Could not parse 'hyprctl' output.")

    monitors_data_raw = []
    for m in monitor_data:
        width = m["width"]
        height = m["height"]
        transform = m.get("transform", 0)

        if transform % 2 != 0: # Handle rotation
            width, height = height, width

        width_cm = m.get("physicalWidth", 0) / 10
        height_cm = m.get("physicalHeight", 0) / 10

        monitors_data_raw.append({
            "name": m["name"],
            "width": width,
            "height": height,
            "x_px": m["x"],
            "y_px": m["y"],
            "width_cm": width_cm,
            "height_cm": height_cm,
            "x_cm": 0.0, 
            "y_cm": 0.0
        })

    if align == 'none':
        monitors_to_dump = monitors_data_raw
    elif align == 'vertical':
        monitors_data_raw.sort(key=lambda m_item: m_item["y_px"])
        total_width_cm = max(m_item["width_cm"] for m_item in monitors_data_raw)
        current_y_cm = 0.0
        for m_item in monitors_data_raw:
            m_item["y_cm"] = current_y_cm
            current_y_cm += m_item["height_cm"]
            m_item["x_cm"] = (total_width_cm - m_item["width_cm"]) / 2
        monitors_to_dump = monitors_data_raw
    elif align == 'horizontal':
        monitors_data_raw.sort(key=lambda m_item: m_item["x_px"])
        total_height_cm = max(m_item["height_cm"] for m_item in monitors_data_raw)
        current_x_cm = 0.0
        for m_item in monitors_data_raw:
            m_item["x_cm"] = current_x_cm
            current_x_cm += m_item["width_cm"]
            m_item["y_cm"] = (total_height_cm - m_item["height_cm"]) / 2
        monitors_to_dump = monitors_data_raw

    for m_item in monitors_to_dump:
        if "x_px" in m_item: del m_item["x_px"]
        if "y_px" in m_item: del m_item["y_px"]
    
    with open(monitor_file, "w") as f:
        yaml.dump(monitors_to_dump, f, sort_keys=False)

def process_image(image_path: Path, monitors, output_path: Path, format: str, 
                 no_scale: bool, actual_monitor_sizes: bool, offset: str = None,
                 bounds=None):
    
    if not image_path.is_file():
        return

    try:
        im = Image.open(image_path)
    except UnidentifiedImageError:
        tqdm.write(f"could not open file {image_path}, skipping...")
        return

    if bounds is None:
         min_x, min_y, max_x, max_y, max_pixels_per_cm_x, max_pixels_per_cm_y = get_monitor_bounds(monitors, actual_monitor_sizes)
    else:
         min_x, min_y, max_x, max_y, max_pixels_per_cm_x, max_pixels_per_cm_y = bounds

    total_width, total_height = max_x - min_x, max_y - min_y
    
    width, height = im.size
    if no_scale and not (width >= total_width and height >= total_height):
        tqdm.write(f"image {image_path} is to small, skipping...")
        return

    elif not no_scale:
        scale_x = total_width / width
        scale_y = total_height / height
        scale = max(scale_x, scale_y)
        if scale != 1:
            im = im.resize((int(ceil(width * scale)), int(ceil(height * scale))))
            scaling_direcion = "up" if scale >= 1 else "down"
            tqdm.write(f"scaled {image_path.stem} {scaling_direcion} to {im.size}, scaling factor = {scale:.02}")

    width, height = im.size

    if offset:
        try:
            ox, oy = map(int, offset.split(","))
            offset_x = ox
            offset_y = oy
            tqdm.write(f"Using manual offset: {offset_x}, {offset_y}")
        except ValueError:
            tqdm.write("Error: Offset must be in format 'x,y'")
            sys.exit(1)
    else:
        offset_x = int(width / 2 - total_width / 2) - min_x
        offset_y = int(height / 2 - total_height / 2) - min_y

    os.makedirs(output_path / image_path.stem, exist_ok=True)

    for m in monitors:
        if actual_monitor_sizes:
            x_l = offset_x + int(m["x_cm"] * max_pixels_per_cm_x)
            x_r = x_l + int(m["width_cm"] * max_pixels_per_cm_x)
            y_u = offset_y + int(m["y_cm"] * max_pixels_per_cm_y)
            y_l = y_u + int(m["height_cm"] * max_pixels_per_cm_y)
            cropped = im.crop((x_l, y_u, x_r, y_l))
            cropped = cropped.resize((m["width"], m['height']))
        else:
            x_l = offset_x + m["x"]
            x_r = x_l + m["width"]
            y_u = offset_y + m["y"]
            y_l = y_u + m["height"]
            cropped = im.crop((x_l, y_u, x_r, y_l))

        filename = f"{image_path.stem}_{m['name']}.{format}"
        cropped.save(output_path / image_path.stem / filename)
