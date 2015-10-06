#!/usr/bin/env python

import alsaaudio
import collections
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from configparser import ConfigParser
from datetime import datetime
from glob import glob
from queue import Queue

try:
    from pynvml import *
except ImportError:
    _NVIDIA_SUPPORT = False
else:
    _NVIDIA_SUPPORT = True

# Set default global values
_DEF_REFRESH = 10  # Seconds
_DEF_STRFTIME = '%a %Y-%m-%d %H:%M'
_PACMAN_CACHE_DIR = '/var/cache/pacman/pkg'
COLORS = {
    'CYAN':   '#00FFFF',
    'GREEN':  '#00FF00',
    'RED':    '#FF0000',
    'WHITE':  '#FFFFFF',
    'YELLOW': '#FFFF00',
}

class WorkerThread(threading.Thread):
    def __init__(self, args):
        super().__init__()
        self.output = None
        self.args = args

class Volume(WorkerThread):
    """Check the volume level percentage"""

    def run(self):
        try:
            mixer = alsaaudio.Mixer()#cardindex=1)
            volumes = mixer.getvolume()
        except alsaaudio.ALSAAudioError:
            percentage = 'ERROR'
            instance = None
            color = COLORS['RED']
        else:
            percentage = str(int(sum(volumes) / len(volumes)))
            stats = (mixer.cardname(), mixer.mixer(), str(mixer.mixerid()))
            instance = '.'.join(stats)
            color = COLORS['WHITE']
        self.output = {
            'name':      'volume',
            'instance':  instance,
            'full_text': ' ♫ {}% '.format(percentage),
            'separator': False,
            'color':     color,
        }


class DiskFree(threading.Thread):
    """Check free disk space in human readable units"""

    def __init__(self, mount):
        threading.Thread.__init__(self)
        self.mount = mount
        self.output = None

    def run(self):
        stat = os.statvfs(self.mount)
        free = stat.f_bavail * stat.f_frsize
        self.output = {
            'name':      'disk_info',
            'instance':  self.mount,
            'full_text': ' {}: {} '.format(self.mount, _hr_diskspace(free)),
            'separator': False,
        }


class WANConnection(threading.Thread):
    """Open a test URL and output the status of the request."""

    def __init__(self, testaddr):
        threading.Thread.__init__(self)
        self.testaddr = testaddr
        self.output = None

    def run(self):
        try:
            dns_lookup_test = socket.gethostbyname(self.testaddr)
        except OSError:
            status = 'DOWN'
            color = COLORS['RED']
        else:
            status = 'UP'
            color = COLORS['GREEN']
        self.output = {
            'name':      'wan_connection',
            'full_text': ' WAN: {} ' .format(status),
            'color':     color,
            'separator': False,
        }

class GPUStats(threading.Thread):
    """Check GPU temperature and fan speed"""

    def __init__(self, gpuindex=0):
        threading.Thread.__init__(self)
        self.gpuindex = gpuindex
        self.output = None

    def run(self):
        handle = nvmlDeviceGetHandleByIndex(self.gpuindex)
        temperature = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
        fan_speed = nvmlDeviceGetFanSpeed(handle)
        self.output = {
            'name':      'gpu_stats',
            'full_text': ' GPU: {}°C {}%'.format(temperature, fan_speed),
            'separator': False,
        }


def load(args):
    with open('/proc/loadavg') as loadfile:
        load_str = ' '.join(loadfile.read().split()[:3])

    return {
        'name':      args['function'],
        'full_text': args['format'].format(load_str),
        'separator': args['separator'],
    }

def date_time(args):
    return {
        'name':      args['function'],
        'full_text': datetime.now().strftime(args['format']),
        'separator': args['separator'],
    }

def uptime(args):
    with open('/proc/uptime') as upfile:
        uptime_str = _hr_time(int(upfile.read().split('.')[0]))

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(uptime_str),
        'separator': args['separator'],
    }

def pacman_updates(args):
    """Check how many system updates are available"""

    try:
        packages = subprocess.check_output('checkupdates').splitlines()
    except subprocess.CalledProcessError as err:
        print(err)
        sys.exit(1)

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(package_count),
        'separator': args['separator'],
    }


def file_count(args):
    """This function requires a directory path. Optional arguments are a string
       to glob and color thresholds.

       Returns the total file count of a directory matching an optional pattern
    """

    try:
        files = glob(os.path.join(args['directory'], args['pattern']))
    except KeyError:
        files = os.listdir(args['directory'])
    file_count = len(files)

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(file_count),
        'separator': args['separator'],
    }

def _hr_diskspace(bytes):
    """Convert bytes to a human readable string"""

    kbytes = bytes // 1024
    if not kbytes:
        return '{} B'.format(bytes)
    mbytes = kbytes // 1024
    if not mbytes:
        return '{} KB'.format(kbytes)
    gbytes = mbytes // 1024
    if not gbytes:
        return '{} MB'.format(mbytes)
    tbytes = gbytes // 1024
    if not tbytes:
        return '{} GB'.format(gbytes)
    else:
        return '{} TB'.format(tbytes)

def _hr_time(seconds):
    """Convert time in seconds to a human readable string"""

    minutes = seconds // 60
    if not minutes:
        return '{}s'.format(seconds)
    hours = minutes // 60
    if not hours:
        seconds -= minutes * 60
        return '{}m {}s'.format(minutes, seconds)
    days = hours // 24
    if not days:
        minutes -= hours * 60
        return '{}h {}m'.format(hours, minutes)
    years = days // 365
    if not years:
        hours -= days * 24
        return '{}d {}h'.format(days, hours)
    else:
        days -= years * 365
        return '{}y {}d'.format(years, days)

def main():
    if _NVIDIA_SUPPORT:
        nvmlInit()

    # Get the JSON ball rolling
    json_seps = (',', ':')
    version = {"version": 1}
    version_str = json.dumps(version, separators=json_seps)
    print(version_str, '[', sep='\n', flush=True)

    # Initialize the worker threads
    worker_threads = (
        PacmanCache(),
        GPUStats(),
        WANConnection('google.com'),
        DiskFree('/'),
        DiskFree('/home'),
        Load(),
        Uptime(),
        Volume(),
        CurrentTime(),
    )
    for worker_thread in worker_threads:
        worker_thread.start()

    while True:
        # Wait for threads to finish their runs
        while threading.activeCount() > 1:
            pass

        # Assemble the JSON string and dump it to the screen
        bar_data = [worker_thread.output for worker_thread in worker_threads]
        json_data = json.dumps(bar_data, separators=json_seps)
        print(json_data, ',', sep='\n', flush=True)
        time.sleep(_DEF_REFRESH)

        # Run the threads again to get new data
        for worker_thread in worker_threads:
            worker_thread.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('\n')
