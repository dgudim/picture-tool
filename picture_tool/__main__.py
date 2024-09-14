#!/usr/bin/env python3

import os, subprocess
import click
import shutil
import inquirer

from pykakasi import Kakasi
from urllib.parse import urlparse

from jsonpath_ng import parse
import json

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
SEPARATOR=os.environ.get('TOOL_SEPARATOR', '_')

@click.command()
@click.option('--links-file', '-l',
              default=lambda: os.environ.get('TOOL_LINKS_FILE', 'links.txt'),
              help='File that contains links to artstation posts.')
@click.option('--destination-folder', '-d',
              default=lambda: os.environ.get('TOOL_DESTINATION_FOLDER', ''),
              help='Folder where pictures would be placed.')
@click.option('--postfix', '-p',
              default='artstation',
              help='Postfix of destination folders inside folders. If not defined uses link source as base (artstation)')
@click.option('--interactive', '-i', is_flag=True, 
              help='Prompt if name contains forbidden chars.')
@click.option('--no-suppress-output', is_flag=True, 
              help='Prompt if name contains forbidden chars.')
def download(links_file: str, destination_folder: str, postfix: str, interactive: str, no_suppress_output: str):
    """This command downloads pictures from artstation."""    
    
    STDOUT=subprocess.DEVNULL
    
    if no_suppress_output:
        STDOUT=subprocess.STDOUT
    
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)
        
    f_links = open(links_file, 'r')
    try:
        subprocess.run(['gallery-dl', '-v'], stdout=STDOUT, stderr=STDOUT)
    except subprocess.CalledProcessError as grepexc:
        print("Error running gallery-dl -v", grepexc.returncode, grepexc.output)

    while True:
        link = f_links.readline()
        if not link:
            break
        
        link = link[:-1]
        
        json_output = subprocess.check_output(['gallery-dl', link, '-j'])
        
        json_info = json.loads(json_output)
        expr = parse('$..username')
        
        found_username = next(iter(expr.find(json_info)), None)
        username = '__unknown__' if found_username == None else found_username.value
        
        destination = os.path.join(destination_folder, f'{username}_{postfix}')
        
        if not os.path.exists(destination):
            os.makedirs(destination)
        
        parsed_links = subprocess.check_output(['gallery-dl', link, '-g']).decode("utf-8")
        download_links = [l for l in parsed_links.split('\n') if len(l) > 0 and not l.startswith('|')]
        
        
        if interactive and len(download_links) > 1:
            CHECKBOX_NAME = 'images'
            questions = [
                inquirer.Checkbox(
                    CHECKBOX_NAME,
                    message=f'Multiple images found at {link}. Select images to download',
                    carousel=True,
                    choices=download_links,
                ),
            ]

            download_links = inquirer.prompt(questions)[CHECKBOX_NAME]

            print(f"You selected {download_links}")
            
        for download_link in download_links:
            parsed_link = urlparse(download_link)
            
            filename = os.path.basename(parsed_link.path)
            
            query_args = parsed_link.query.split('&')
            if len(query_args) > 0:
                filename = '_'.join([query_args[0], filename])
            
            print(f"Downloading {link} filename={filename} author={username}")
            
            filename = os.path.join(destination, filename)
            subprocess.run(['wget', '-O', filename, download_link], stdout=STDOUT, stderr=STDOUT)
    
    f_links.close()


@click.command()
@click.option('--source-folder', '-s',
              default=lambda: os.environ.get('TOOL_SOURCE_FOLDER', '.'),
              help='Folder where folders with pictures are located.')
@click.option('--destination-folder', '-d', 
              default=lambda: os.environ.get('TOOL_DESTINATION_FOLDER', ''),
              help='Folder where pictures would be placed.')
@click.option('--interactive', '-i', is_flag=True, 
              help='Prompt if name contains forbidden chars.')
@click.option('--postfix', '-p', 
              default='pixiv',
              help='Postfix of destination folders inside folders')
def move(source_folder: str, destination_folder: str, postfix: str, interactive: bool):
    """This command moves pictures from one folder to another."""
    if not os.path.isdir(source_folder):
        print("Please enter valid source_folder")
        return
    
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)
    converter = Kakasi()
    subfolders = [ f for f in os.scandir(source_folder) if f.is_dir() ]
    for folder in subfolders:
        entries = folder.name.split(SEPARATOR)
        
        name = SEPARATOR.join(entries[:-1])
        pixiv_id = entries[-1]
        
        if not name.isascii():
            recommended_name = "".join([ item['hepburn'] for item in converter.convert(name) ])
            new_name = recommended_name
            
            if interactive:
                print(f"Author {name} contains non-ascii characters, please provide a new name or use default [{recommended_name}]:")
                user_name = input()
                
                if user_name:
                    new_name = user_name
                
            name = new_name
        destination_name = f"{name}_id{pixiv_id}_{postfix}"        
        shutil.move(folder.path, os.path.join(destination_folder, destination_name))


@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    """This tool can move pictures from one folder to another, or download pictures from artstation."""
    pass


cli.add_command(download)
cli.add_command(move)

if __name__ == '__main__':
    cli()