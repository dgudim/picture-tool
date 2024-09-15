#!/usr/bin/env python3

import json
import os
from pathlib import Path
import random
import shutil
import string
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import re
import hashlib

import click
import inquirer
from jsonpath_ng import parse
from loguru import logger
from pykakasi import Kakasi

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
SEPARATOR = os.environ.get("TOOL_SEPARATOR", "_")

AUTHOR_MAPPING_FILE = Path(
    os.path.dirname(os.path.realpath(__file__)), "author_mapping.json"
)
AUTHOR_MAPPING: dict[str, str] = {}


def sha256sum(filename: Path):
    return hashlib.sha256(filename.read_bytes()).hexdigest()


def strip_link(link: str):
    return link.strip().split("?")[0]


def ensure_author_mapping_loaded():
    if not AUTHOR_MAPPING_FILE.exists():
        AUTHOR_MAPPING_FILE.write_text("{}", encoding="utf-8")

    global AUTHOR_MAPPING
    AUTHOR_MAPPING = json.loads(AUTHOR_MAPPING_FILE.read_text(encoding="utf-8"))


def get_author_mapping(author: str):
    ensure_author_mapping_loaded()
    global AUTHOR_MAPPING
    return AUTHOR_MAPPING.get(author, None)


def set_author_mapping(author: str, maps_to: str):
    ensure_author_mapping_loaded()
    global AUTHOR_MAPPING
    AUTHOR_MAPPING[author] = maps_to

    AUTHOR_MAPPING_FILE.write_text(json.dumps(AUTHOR_MAPPING), encoding="utf-8")


def get_or_prompt_username_mapping(original: str, recommended: str) -> str:
    if (existing := get_author_mapping(original)) is not None:
        return existing

    print(f"{original} has no mapping. Input a new name or accept [{recommended}]:")
    mapped = (input() or "").strip()
    ret = mapped if len(mapped) > 0 else recommended
    set_author_mapping(original, ret)
    return ret


@click.command()
@click.option(
    "--links-file",
    "-l",
    default=lambda: os.environ.get("TOOL_LINKS_FILE", "links.txt"),
    help="File that contains links to artstation posts.",
)
@click.option(
    "--destination-folder",
    "-d",
    default=lambda: os.environ.get("TOOL_DESTINATION_FOLDER", ""),
    help="Folder where pictures would be placed.",
)
@click.option(
    "--no-suppress-output",
    is_flag=True,
    help="Prompt if name contains forbidden chars.",
    default=True,
)
def download(
    links_file_path: str,
    destination_folder: str,
    no_suppress_output: bool,
):
    """This command downloads pictures from artstation."""

    links_source_file = Path(links_file_path)

    STDOUT = subprocess.STDOUT if no_suppress_output else subprocess.DEVNULL

    os.makedirs(destination_folder, exist_ok=True)

    try:
        subprocess.run(["gallery-dl", "-v"], stdout=STDOUT, stderr=STDOUT, check=True)
    except subprocess.CalledProcessError as grepexc:
        logger.error("Error running gallery-dl -v", grepexc.returncode, grepexc.output)

    all_links = [
        lst
        for link in links_source_file.read_text(encoding="utf-8").split("\n")
        if len(lst := strip_link(link)) > 0
    ]

    direct_links = [
        link
        for link in all_links
        if re.fullmatch(r"https://cdn.\.artstation.com/p/assets/images/images.*", link)
    ]
    indirect_links = [
        link
        for link in all_links
        if re.fullmatch(r"https://.*?artstation\.com/artwork/.+", link)
    ]
    unknown_links = [
        link
        for link in all_links
        if (link not in direct_links and link not in indirect_links)
    ]

    if len(unknown_links) > 0:
        logger.warning(f"{len(unknown_links)} are unknown")

    for link in indirect_links:
        link_info = json.loads(subprocess.check_output(["gallery-dl", link, "-j"]))

        expr = parse("$..username")

        username = next(iter(expr.find(link_info)), None)

        if username is None:
            logger.error("Username not found for {link}")
            continue

        author = get_or_prompt_username_mapping(username, username)

        destination_subfolder = Path(destination_folder, f"{author}_artstation")
        os.makedirs(destination_subfolder, exist_ok=True)

        gallery_dl_raw_links = subprocess.check_output(
            ["gallery-dl", link, "-g"]
        ).decode("utf-8")
        resolved_links = [
            lnk
            for link in gallery_dl_raw_links.split("\n")
            if len(lnk := link.strip()) > 0
            and not lnk.startswith(
                "|"
            )  # Skip medium/low quality images from gallery-dl
        ]

        links_to_download = [
            link for link in resolved_links if strip_link(link) in indirect_links
        ]  # If a resolved link was found in the list, use that and skip selection

        if len(resolved_links) > 1 and len(links_to_download) == 0:
            checkbox_name = "images"
            questions = [
                inquirer.Checkbox(
                    checkbox_name,
                    message=f"Multiple images found at {link}. Select images to download",
                    carousel=True,
                    choices=resolved_links,
                ),
            ]

            links_to_download = inquirer.prompt(questions)[checkbox_name]

            logger.info(f"You selected: {links_to_download}")

        for download_link in links_to_download:
            filename = os.path.basename(urlparse(download_link).path)

            logger.info(f"Downloading {link} filename={filename} author={username}")

            with TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir, filename)
                final_path = Path(destination_subfolder, filename)
                subprocess.run(
                    ["wget", "-O", temp_path, download_link],
                    stdout=STDOUT,
                    stderr=STDOUT,
                    check=True,
                )
                if not final_path.exists():
                    temp_path.rename(final_path)
                    logger.info(f"{temp_path} -> {final_path}")
                    return

                orig_stem = final_path.stem
                temp_hash = sha256sum(temp_path)

                i = 1
                while final_path.exists():
                    logger.warning(f"{final_path} already exists")

                    target_hash = sha256sum(final_path)

                    if target_hash == temp_hash:
                        logger.warning("Hashes match, not moving")
                        return

                    logger.warning("Hashes don't match, adding postfix")
                    final_path = final_path.with_stem(
                        f"{orig_stem}_{i}"
                    )
                    i += 1

                temp_path.rename(final_path)
                logger.info(f"{temp_path} -> {final_path}")

    # We are done here, save unknown links
    links_source_file.write_text("\n".join(unknown_links), encoding="utf-8")


@click.command()
@click.option(
    "--source-folder",
    "-s",
    default=lambda: os.environ.get("TOOL_SOURCE_FOLDER", "."),
    help="Folder where source folders with pictures are located.",
)
@click.option(
    "--destination-folder",
    "-d",
    default=lambda: os.environ.get("TOOL_DESTINATION_FOLDER", ""),
    help="Folder where pictures would be placed.",
)
@click.option(
    "--postfix",
    "-p",
    default="pixiv",
    help="Postfix of destination folders inside folders",
)
def move_pixiv(source_folder: str, destination_folder: str, postfix: str):
    """This command moves pictures from one folder to another."""
    if not os.path.isdir(source_folder):
        logger.error("Please enter valid source_folder")
        return

    os.makedirs(destination_folder, exist_ok=True)

    converter = Kakasi()
    subfolders = [f for f in os.scandir(source_folder) if f.is_dir()]

    for folder in subfolders:
        parts = folder.name.split(SEPARATOR)  # <author_name>_<id>

        name = SEPARATOR.join(parts[:-1])
        pixiv_id = parts[-1]

        recommended_name = (
            name
            if name.isascii()
            else "".join([item["hepburn"] for item in converter.convert(name)])
        )

        author = get_or_prompt_username_mapping(name, recommended_name)

        destination_name = (
            f"{author}_id{pixiv_id}_{postfix}"  # TODO: Match by id in the destination
        )
        shutil.move(folder.path, Path(destination_folder, destination_name))


@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    """This tool can move pictures from one folder to another, or download pictures from artstation."""
    pass


cli.add_command(download)
cli.add_command(move_pixiv)

if __name__ == "__main__":
    cli()
