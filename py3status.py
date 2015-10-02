#!/usr/bin/env python

"""
Author: Charles Ferrari
https://github.com/ferrari8608

            DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
                    Version 2, December 2004

 Copyright (C) 2004 Sam Hocevar <sam@hocevar.net>

 Everyone is permitted to copy and distribute verbatim or modified
 copies of this license document, and changing it is allowed as long
 as the name is changed.

            DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
   TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION

  0. You just DO WHAT THE FUCK YOU WANT TO.
"""

import alsaaudio
import collections
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pynvml import *

# Set default global values
_DEF_REFRESH = 10  # Seconds
_DEF_STRFTIME = '%a %Y-%m-%d %H:%M'
_DEF_TEST_ADDRESS = 'https://www.google.com'
_DEF_TIMEOUT = 0.1  # Seconds
_PACMAN_CACHE_DIR = '/var/cache/pacman/pkg'
COLORS = {
    'CYAN':   '#00FFFF',
    'GREEN':  '#00FF00',
    'RED':    '#FF0000',
    'WHITE':  '#FFFFFF',
    'YELLOW': '#FFFF00',
}

class GenericWorkerThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.output = None

class Volume(GenericWorkerThread):
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


class Uptime(GenericWorkerThread):
    """Check the OS uptime"""

    def run(self):
        with open('/proc/uptime') as upfile:
            uptime_str = _hr_time(int(upfile.read().split('.')[0]))
        self.output = {
            'name':      'uptime',
            'full_text': ' UPTIME: {} '.format(uptime_str),
            'separator':  False,
        }


class Load(GenericWorkerThread):
    """Check the current system load"""

    def run(self):
        with open('/proc/loadavg') as loadfile:
            load_str = ' '.join(loadfile.read().split()[:3])
        self.output = {
            'name':      'load',
            'full_text': ' LOAD: {} '.format(load_str),
            'separator': False,
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


class CurrentTime(threading.Thread):
    """Check the current time and output in the specified format"""

    def __init__(self, timeform=_DEF_STRFTIME):
        threading.Thread.__init__(self)
        self.timeform = timeform
        self.output = None

    def run(self):
        self.output = {
            'name':      'time',
            'full_text': ' {1:{0}} '.format(self.timeform, datetime.now()),
            'separator': False,
            'color':     '#00FFFF',
        }


class WANConnection(threading.Thread):
    """Open a test URL and output the status of the request."""

    def __init__(self, testaddr=_DEF_TEST_ADDRESS):
        threading.Thread.__init__(self)
        self.testaddr = testaddr
        self.output = None

    def run(self):
        try:
            urllib.request.urlopen(testaddr, timeout=_DEF_TIMEOUT)
        except urllib.request.URLError:
            status = 'DOWN'
            color = COLORS['RED']
        except:
            status = 'ERROR'
            color =  COLORS['YELLOW']
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


class Updates(GenericWorkerThread):
    """Check how many system updates are available"""

    def run(self):
        packages = subprocess.check_output('checkupdates').splitlines()
        package_count = len(packages)
        if package_count:
            color = COLORS['YELLOW']
        else:
            color = COLORS['GREEN']
        self.output = {
            'name':      'updates',
            'full_text': ' UPDATES: {} '.format(package_count),
            'color':     color,
            'separator': False,
        }


class PacmanCache(GenericWorkerThread):
    """Check how many package files are in the pacman cache directory"""

    def run(self):
        files = len(os.listdir(_PACMAN_CACHE_DIR))
        self.output = {
            'name':      'pacman_cache',
            'full_text': ' PACMAN CACHE: {} '.format(files),
            'separator': False,
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
    nvmlInit()  # Required for Nvidia GPU stats
    json_seps = (',', ':')
    version = {"version": 1}
    version_str = json.dumps(version, separators=json_seps)
    print(version_str, '[', sep='\n', flush=True)

    # Initialize the worker threads
    worker_threads = (
        Updates(),
        PacmanCache(),
        GPUStats(),
#        WANConnection(),  # Stopped working correctly around when
        DiskFree('/'),     # threading was implemented. Not sure why.
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
