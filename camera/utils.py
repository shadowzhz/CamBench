import os
import re
import subprocess


def normalize_format(pixel_format):

    if pixel_format in {
        "YUYV",
        "YUY2"
    }:
        return "YUY2"

    return pixel_format



def device_sort_key(path):

    match = re.search(
        r"video(\d+)$",
        path
    )

    if match:
        return int(match.group(1))

    return 9999



def run_cmd(args, timeout=4):

    try:

        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )

        return result.stdout


    except (
        FileNotFoundError,
        subprocess.TimeoutExpired
    ):

        return ""



def parse_field(
    text,
    field_name,
    default=""
):

    match = re.search(
        rf"{re.escape(field_name)}\s*:\s*(.+)",
        text
    )

    if match:
        return match.group(1).strip()

    return default



def parse_device_caps(text):

    lines = text.splitlines()

    caps = []

    active = False


    for line in lines:

        if re.search(
            r"Device Caps\s*:",
            line
        ):
            active = True
            continue


        if not active:
            continue


        if not line.startswith(
            (" ", "\t")
        ):
            break


        item = line.strip()

        if item:
            caps.append(item)


    return caps



def is_video_capture_node(text):

    caps = parse_device_caps(text)


    if caps:

        return any(
            c in {
                "Video Capture",
                "Video Capture Multiplanar"
            }
            for c in caps
        )


    return bool(
        re.search(
            r"^\s*Video Capture(?: Multiplanar)?\s*$",
            text,
            re.MULTILINE
        )
    )



def camera_device_present(camera):

    return any(
        os.path.exists(device)
        for device in camera.device_candidates
    )
