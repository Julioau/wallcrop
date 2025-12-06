import os
import yaml
import json
import subprocess
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from math import ceil
import click
from tqdm import tqdm
import sys


@click.command("wallcrop",
help="A tool for cropping an image into smaller images for use as individual desktop wallpapers",
context_settings=dict(help_option_names=["-h", "--help"]),)
@click.option(
    "-m",
    "--monitors",
    "monitor_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default="./monitors.yml",
    show_default=True
)
@click.option(
    "-c",
    "--create-monitors",
    is_flag=True,
    help="Create monitors.yml from hyprctl monitors -j"
)
@click.option(
    "--offset",
    type=str,
    help="Manual offset x,y for the crop origin (e.g. '0,0')"
)
@click.option(
    "--align",
    type=click.Choice(['none', 'vertical', 'horizontal'], case_sensitive=False),
    default='none',
    show_default=True,
    help="Automatic alignment for x_cm and y_cm when creating monitors.yml"
)
@click.option(
    "-n",
    "--no_scale",
    is_flag=True,
    help="Disables Scaling of Input Image. If Image is too small, it will be skipped",
)
@click.option("-a", "--actual-monitor-sizes", is_flag=True, help="crop using actual monitor sizes, not just to make pixels fit")
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(file_okay=False, path_type=Path),
    default="./wallcrop",
    show_default=True
)
@click.option(
    "-f", "--format", type=click.STRING, default="png", help="file format of the cropped images",show_default=True
)
@click.argument("input_file", nargs=-1, type=click.Path(exists=True, path_type=Path))
def main(monitor_file: Path, output_path: Path, no_scale: bool, input_file: tuple[Path], format: str, actual_monitor_sizes: bool, create_monitors: bool, offset: str, align: str):
    if create_monitors:
        try:
            result = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            # Determine start of JSON array
            json_start = output.find('[')
            if json_start != -1:
                output = output[json_start:]
            monitor_data = json.loads(output)
        except (subprocess.CalledProcessError, FileNotFoundError):
            tqdm.write("Error: Could not run 'hyprctl monitors -j'. Are you using Hyprland?")
            sys.exit(1)
        except json.JSONDecodeError:
            tqdm.write("Error: Could not parse 'hyprctl' output.")
            sys.exit(1)

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
                "x_px": m["x"], # Store original pixel coordinates for alignment calculation
                "y_px": m["y"],
                "width_cm": width_cm,
                "height_cm": height_cm,
                "x_cm": 0.0, # Will be set by alignment logic
                "y_cm": 0.0  # Will be set by alignment logic
            })

        if align == 'none':
            monitors_to_dump = monitors_data_raw
        elif align == 'vertical':
            # Sort by y_px to stack them from top to bottom
            monitors_data_raw.sort(key=lambda m_item: m_item["y_px"])
            
            total_width_cm = max(m_item["width_cm"] for m_item in monitors_data_raw)
            current_y_cm = 0.0
            
            for m_item in monitors_data_raw:
                # Vertical stacking
                m_item["y_cm"] = current_y_cm
                current_y_cm += m_item["height_cm"]
                
                # Horizontal centering
                m_item["x_cm"] = (total_width_cm - m_item["width_cm"]) / 2
            monitors_to_dump = monitors_data_raw
            
        elif align == 'horizontal':
            # Sort by x_px to place them from left to right
            monitors_data_raw.sort(key=lambda m_item: m_item["x_px"])
            
            total_height_cm = max(m_item["height_cm"] for m_item in monitors_data_raw)
            current_x_cm = 0.0

            for m_item in monitors_data_raw:
                # Horizontal placement
                m_item["x_cm"] = current_x_cm
                current_x_cm += m_item["width_cm"]
                
                # Vertical centering
                m_item["y_cm"] = (total_height_cm - m_item["height_cm"]) / 2
            monitors_to_dump = monitors_data_raw

        # Remove temporary pixel coordinates before dumping
        for m_item in monitors_to_dump:
            if "x_px" in m_item:
                del m_item["x_px"]
            if "y_px" in m_item:
                del m_item["y_px"]
        
        with open(monitor_file, "w") as f:
            yaml.dump(monitors_to_dump, f, sort_keys=False)
        tqdm.write(f"Successfully created {monitor_file}")
        return

    if not monitor_file.exists():
        tqdm.write(f"Error: Monitor file '{monitor_file}' not found.")
        sys.exit(1)

    with open(monitor_file) as f:
        monitors = yaml.safe_load(f)

    # calculate necessary source image size
    if actual_monitor_sizes:
        try:
            max_pixels_per_cm_x = max([m["width"]/m["width_cm"] for m in monitors])
            max_pixels_per_cm_y = max([m["height"]/m["height_cm"] for m in monitors])

            min_x = int(min([m["x_cm"] * max_pixels_per_cm_x for m in monitors]))
            min_y = int(min([m["y_cm"]  * max_pixels_per_cm_y for m in monitors]))
            max_x = int(max([(m["x_cm"] + m["width_cm"]) * max_pixels_per_cm_x for m in monitors]))
            max_y = int(max([(m["y_cm"] + m["height_cm"]) * max_pixels_per_cm_y for m in monitors]))
        except KeyError:
            tqdm.write(f"ERROR: in order to use the actual monitor size option, each monitor needs the keys width (in px), height (in px), width_cm, height_cm, x_cm, y_cm")
            sys.exit(-1)
            
        tqdm.write(f"pixels per cm: ({max_pixels_per_cm_x}x{max_pixels_per_cm_y})")

        for m in monitors:
            tqdm.write(f"{m["name"]}")
            tqdm.write(f"scaled size {m['width_cm']*max_pixels_per_cm_x}x{m['height_cm']*max_pixels_per_cm_y}")
    else:
        min_x = min([m["x"] for m in monitors])
        min_y = min([m["y"] for m in monitors])
        max_x = max([m["x"] + m["width"] for m in monitors])
        max_y = max([m["y"] + m["height"] for m in monitors])

    total_width, total_height = max_x - min_x, max_y - min_y
    tqdm.write(f"total screen area: {total_width}x{total_height} px")

    # iterate over all images
    for image_path in tqdm(input_file):

        # ignore directories
        if not image_path.is_file():
            continue

        # ignore invalid image files
        try:
            im = Image.open(image_path)
        except UnidentifiedImageError:
            tqdm.write(f"could not open file {image_path}, skipping...")
            continue

        width, height = im.size
        if no_scale and not (width >= total_width and height >= total_height):
            tqdm.write(f"image {image_path} is to small, skipping...")
            continue

        elif not no_scale:
            # scale image if allowed
            scale_x = total_width / width
            scale_y = total_height / height
            scale = max(scale_x, scale_y)
            if scale != 1:
                im = im.resize((int(ceil(width * scale)), int(ceil(height * scale))))
                scaling_direcion = "up" if scale >= 1 else "down"
                tqdm.write(f"scaled {image_path.stem} {scaling_direcion} to {im.size}, scaling factor = {scale:.02}")

        width, height = im.size

        # calculate offsets
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
            # calculate offsets so image is nicely centered
            offset_x = int(width / 2 - total_width / 2) - min_x
            offset_y = int(height / 2 - total_height / 2) - min_y

        os.makedirs(output_path / image_path.stem, exist_ok=True)

        # iterate over the monitors
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

            filename = f"{image_path.stem}_{m["name"]}.{format}"
            cropped.save(output_path / image_path.stem / filename)



if __name__ == "__main__":
    main()
