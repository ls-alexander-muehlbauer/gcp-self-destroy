#!/usr/bin/python3

"""
This script checks if a GCP instance is still being used by the Circle CI Pipeline that started it.
In case the pipeline is not running anymore the VM instance will self-destroy.

NOTE: This script uses only built-in modules to act as a standalone script with no dependencies required.

The following variables must be passed as metadata, when creating the instance:
    - CIRCLE_API_TOKEN
    - CIRCLE_PIPELINE_ID
    optional:
    - SELF_DESTRUCT_INTERVAL_MINUTES (uses default value if not defined)

You can use this script in the "gcloud compute instances create" command as follows:
    gcloud compute instances create
    self-destruct-01
    --zone=us-central1-c
    --image-family=ubuntu-1804-lts
    --image-project=ubuntu-os-cloud
    --boot-disk-size=200GB
    --scopes=https://www.googleapis.com/auth/compute,https://www.googleapis.com/auth/servicecontrol,https://www.googleapis.com/auth/service.management.readonly,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write,https://www.googleapis.com/auth/trace.append,https://www.googleapis.com/auth/devstorage.read_only
    --metadata SELF_DESTRUCT_INTERVAL_MINUTES=1,CIRCLE_API_TOKEN=${CIRCLE_API_TOKEN},CIRCLE_PIPELINE_ID=${CIRCLE_PIPELINE_ID}
    --metadata-from-file startup-script=gcp-keepalive.py
"""

import json
import logging
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from typing import List

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

DEFAULT_SELF_DESTRUCT_INTERVAL_MIN = os.getenv("DEFAULT_SELF_DESTRUCT_MIN", 2)


def get_instance_metadata(name: str, default_value: str = "") -> str:
    name = name.upper()
    url = f"http://metadata.google.internal/computeMetadata/v1/instance/attributes/{name}"
    headers = {"Metadata-Flavor": "Google"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            result = response.read()
    except Exception:
        result = default_value
    metadata_value = str(result.decode("utf-8"))
    return metadata_value


def get_instance_self_destruct_interval_min() -> int:
    return int(
        get_instance_metadata(
            "SELF_DESTRUCT_INTERVAL_MINUTES",
            str(DEFAULT_SELF_DESTRUCT_INTERVAL_MIN)
        )
    )


def get_circle_api_token() -> str:
    return get_instance_metadata("CIRCLE_API_TOKEN")


def get_circle_pipeline_id() -> str:
    return get_instance_metadata("CIRCLE_PIPELINE_ID")


def get_instance_zone() -> str:
    url = "http://metadata.google.internal/computeMetadata/v1/instance/zone"
    headers = {
        "Metadata-Flavor": "Google",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:
        result = response.read().decode("utf-8")
    instance_zone = str(result).split("/")[-1]
    return instance_zone


def get_work_flows(circle_pipeline_id: str, circle_api_token: str) -> List:
    logger.info("Polling Pipeline Status...")
    url = f"https://circleci.com/api/v2/pipeline/{circle_pipeline_id}/workflow"
    headers = {"Accept": "application/json", "Circle-Token": circle_api_token}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:
        result = response.read().decode("utf-8")
    work_flows = json.loads(result)
    return work_flows.get("items", [])


def should_terminate_vm(work_flows: List) -> bool:
    running_status = ["running"]

    for work_flow in work_flows:
        status = work_flow.get("status", None)
        if status in running_status:
            logger.info("Pipeline is still running.")
            return False

    logger.info("Pipeline has finished.")
    return True


def terminate_vm():
    logger.info("Terminating VM...")
    hostname = socket.gethostname()
    instance_zone = get_instance_zone()
    command = f"gcloud compute instances delete {hostname} --zone={instance_zone}"
    subprocess.check_output(shlex.split(command))


def main():
    circle_api_token = get_circle_api_token()
    circle_pipeline_id = get_circle_pipeline_id()
    self_destruct_interval_min = get_instance_self_destruct_interval_min()

    now = time.time()
    timeout = now + (self_destruct_interval_min * 60)
    while time.time() <= timeout:
        work_flows = get_work_flows(circle_pipeline_id, circle_api_token)
        if should_terminate_vm(work_flows):
            terminate_vm()
        time.sleep(5)
    else:
        terminate_vm()


if __name__ == '__main__':
    main()
