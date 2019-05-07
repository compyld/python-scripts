#!/usr/bin/python3
# Useful script for copying over every image from one Docker registry to another

# Imports for HTTP requests, password input method, regexp, handling arguments, docker and csv export
import requests
from requests.auth import HTTPBasicAuth
import getpass
import re
import argparse
import docker
from docker.errors import APIError, TLSParameterError
import csv

# Status messages for digest comparisons
image_status=["Image doesn't exist on target", "Image already present on target", "Conflict: same tag exist in both registries with different digest"]

# Image array
images = []
# First entry in the array are the headers for CSV export
image_info = {}
image_info['image']="Image"
image_info['tag']="Tag"
image_info['source_digest']="Source digest"
image_info['target_digest']="Target digest"
image_info['status']="Status"
image_info['pull_command']="Pull command"
image_info['retag_command']="Retag command"
image_info['push_command']="Push command"
image_info['cleanup_source']="Cleanup source image"
image_info['cleanup_target']="Cleanup target image"
images.append(image_info)

# CSV export properties
csv_delimiter=","
csv_filename='output.csv'
csv_write=True

# Dry run: if true, it just outputs the docker commands but doesn't run them
dry_run=True

# Argument parsing
parser = argparse.ArgumentParser(description='Copy Docker images from source to target registry')
parser.add_argument('--source-registry', metavar='https://some.registry.com', help='source registry address - including http(s)://', required=True)
parser.add_argument('--source-user', help='User for accessing source registry - leave it blank for anonymous access')
parser.add_argument('--source-password', help='Password for source registry user - will be asked if not provided')
parser.add_argument('--target-registry', metavar='https://some.other.registry.com', help='target registry address - including http(s)://', required=True)
parser.add_argument('--target-user', help='User for accessing target registry - leave it blank for anonymous access')
parser.add_argument('--target-password', help='Password for target registry user - will be asked if not provided')
args = parser.parse_args()

# Creating sessions to handle possible authentication
source_session = requests.Session()
target_session = requests.Session()

# If a user is specified then this makes sure that a password is presented as well
if args.source_user:
    if not args.source_password:
        args.source_password = getpass.getpass('Password for ' + args.source_user + ' user for ' + args.source_registry + ' : ' )
    source_session.auth = (args.source_user, args.source_password)
    source_auth = source_session.post(args.source_registry)
if args.target_user:
    if not args.target_password:
        args.target_password = getpass.getpass('Password for ' + args.target_user + ' user for ' + args.target_registry + ' : ' )
    target_session.auth = (args.target_user, args.target_password)
    target_auth = target_session.post(args.target_registry)

# Requesting repositories list (=images catalog) from source registry
source_catalog = source_session.get(args.source_registry + '/v2/_catalog')
if 'errors' in source_catalog.json():
    for error in source_catalog.json()['errors']:
        print('')
        print('Error connecting to ' + args.source_registry + ':')
        print(error['code'] + ': ' + error['message'])
        exit(1)

# Initializin Docker client and logging in to source and target registries
docker_client = docker.from_env()

if args.source_user and args.source_password:
    try:
        docker_client.login(username=args.source_user, password=args.source_password, registry=args.source_registry)
    except (APIError, TLSParameterError) as err:
        print('')
        print('Could not login to ' + args.source_registry + ':')
        print(err)
        exit(1)
if args.target_user and args.target_password:
    try:
        docker_client.login(username=args.target_user, password=args.target_password, registry=args.target_registry)
    except (APIError, TLSParameterError) as err:
        print('')
        print('Could not login to ' + args.target_registry + ':')
        print(err)
        exit(1)

# Going through the images present in source catalog
for image in source_catalog.json()['repositories']:
    # Getting tags for the images
    tags = source_session.get(args.source_registry + '/v2/' + image + '/tags/list')
    # Going through every tag
    for tag in tags.json()['tags']:
        # Getting the sha256 hash aka digest for comparison
        source_digest_request = source_session.get(args.source_registry + '/v2/' + image + '/manifests/' + tag, headers={"Accept":"application/vnd.docker.distribution.manifest.v2+json"})
        target_digest_request = target_session.get(args.target_registry + '/v2/' + image + '/manifests/' + tag, headers={"Accept":"application/vnd.docker.distribution.manifest.v2+json"})
        source_digest = ""
        target_digest = ""
        if 'Docker-Content-Digest' in source_digest_request.headers:
            source_digest=source_digest_request.headers.get('Docker-Content-Digest')
        if 'Docker-Content-Digest' in target_digest_request.headers:
            target_digest=target_digest_request.headers.get('Docker-Content-Digest')

        # Some modifications for the proper docker commands
        source_registry_plain=re.sub(".*://", "", args.source_registry)
        target_registry_plain=re.sub(".*://", "", args.target_registry)
        source_image=source_registry_plain + '/' + image + ':' + tag
        target_image=target_registry_plain + '/' + image + ':' + tag

        # Storing image info for every image:tag
        image_info = {}
        image_info['image']=image
        image_info['tag']=tag
        image_info['source_digest']=source_digest
        image_info['target_digest']=target_digest
        if not target_digest:
            image_info['status']=image_status[0]
        elif source_digest == target_digest:
            image_info['status']=image_status[1]
        elif source_digest != target_digest:
            image_info['status']=image_status[2]
        image_info['pull_command']='docker pull ' + source_image
        image_info['retag_command']='docker tag ' + source_image + ' ' + target_image
        image_info['push_command']='docker push ' + target_image
        image_info['cleanup_source']='docker rmi '+ source_image
        image_info['cleanup_target']='docker rmi '+ target_image
        images.append(image_info)

# Writing image info to CSV file if asked
if csv_write:
    csv.register_dialect('myOutput',
    delimiter = csv_delimiter,
    quoting=csv.QUOTE_ALL,
    skipinitialspace=True)

    with open(csv_filename, 'w') as csvFile:
        fields = []
        for key in images[0]:
            fields.append(key)
        writer = csv.DictWriter(csvFile, fieldnames=fields, dialect='myOutput')
        writer.writerows(images)

    print("CSV export completed")
    csvFile.close()

if dry_run:
    # Only printing the commands and not running them if dry_run is specified
    print('')
    print('These commands would run:')
    for image in images[1:]:
        if image['status'] == image_status[0]:
            print(image['pull_command'])
            print(image['retag_command'])
            print(image['push_command'])
            print(image['cleanup_source'])
            print(image['cleanup_target'])
            print('')

    # Printing out images:tags, where it is not obvious what should we do
    # (obvious cases: target registry doesn't have such image, target registry has the same image -> digest is the same)
    print('')
    for status_message in image_status[2:]:
        print(status_message)
        for image in images[1:]:
            if image['status'] == status_message:
                print(image['image'] + ':' + image['tag'])
else:
    # TODO: docker pull, retag, push, cleanup commands with python
    docker_client.close()
    exit()

docker_client.close()
