import click
from pathlib import Path
from tqdm import tqdm
import sys
from . import core

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
            core.create_monitor_config(monitor_file, align)
            tqdm.write(f"Successfully created {monitor_file}")
        except RuntimeError as e:
            tqdm.write(f"Error: {e}")
            sys.exit(1)
        return

    try:
        monitors = core.load_monitors(monitor_file)
    except FileNotFoundError as e:
        tqdm.write(f"Error: {e}")
        sys.exit(1)

    # Pre-calculate bounds just to print info, logic is inside process_image too but shared here
    try:
        min_x, min_y, max_x, max_y, _, _ = core.get_monitor_bounds(monitors, actual_monitor_sizes)
    except ValueError as e:
        tqdm.write(f"ERROR: {e}")
        sys.exit(-1)

    total_width, total_height = max_x - min_x, max_y - min_y
    tqdm.write(f"total screen area: {total_width}x{total_height} px")

    # iterate over all images
    for image_path in tqdm(input_file):
        core.process_image(image_path, monitors, output_path, format, no_scale, actual_monitor_sizes, offset)

if __name__ == "__main__":
    main()




if __name__ == "__main__":
    main()
